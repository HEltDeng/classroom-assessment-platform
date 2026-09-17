import io
import os
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-long-enough-for-local-tests")

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main as m
from app.answer_sheets import page_token, parse_page_token
from app.db import Base, get_db
from app.models import Organization, OrganizationSettings, OrganizationMember, User, MemberRole, StudentQRCode, ScanRecord
from app.scan_worker import process_scan
from app.security import hash_password


@pytest.fixture
def classroom(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(m.settings, "scan_storage_dir", str(tmp_path))
    with factory() as db:
        org = Organization(name="卡片测试", code_prefix="YC")
        org.settings = OrganizationSettings(organization_name="卡片测试", student_code_label="编号")
        org.members.append(OrganizationMember(user=User(email="cards@example.com", display_name="测试", password_hash=hash_password("test-password")), login_name="tester", role=MemberRole.OWNER))
        db.add(org); db.commit()
    def override():
        with factory() as db:
            yield db
    m.app.dependency_overrides[get_db] = override
    with TestClient(m.app) as client:
        login = client.post('/api/v1/auth/login', json={"organization_name":"卡片测试", "teacher_login_name":"tester", "password":"test-password"})
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        c = client.post('/api/v1/classes', headers=headers, json={"name":"测试班"}).json()
        students = client.post(f'/api/v1/classes/{c["id"]}/students', headers=headers, json={"students":[{"student_code":"YC0001", "name":"示例学生"}]}).json()
        student = client.get(f'/api/v1/classes/{c["id"]}',headers=headers).json()['students'][0]
        created = client.post('/api/v1/sessions', headers=headers, json={"class_id":c['id'],"name":"双面测试","question_count":2,"answer_keys":[{"question_no":1,"value":"B"},{"question_no":2,"value":"because","question_type":"OCR_SHORT_ANSWER"} ]})
        assert created.status_code == 201, created.text
        exam = created.json()
        client.post(f'/api/v1/sessions/{exam["id"]}/start',headers=headers)
        yield client, headers, c, student, exam, factory
    m.app.dependency_overrides.clear()
    engine.dispose()


def test_print_closed_scan_merge_review_and_archive(classroom):
    client, headers, c, student, exam, factory = classroom
    path=f'/api/v1/students/{student["id"]}/answer-card'
    first=client.get(path,headers=headers)
    assert first.status_code==200, first.text
    assert first.json()==client.get(path,headers=headers).json()
    pdf=client.get(f'/api/v1/classes/{c["id"]}/answer-sheets.pdf',headers=headers)
    assert pdf.status_code==200 and pdf.content.startswith(b'%PDF')
    assert client.get(path).status_code==401
    assert client.post(f'/api/v1/sessions/{exam["id"]}/close',headers=headers).status_code==200
    assert exam['id'] in [s['id'] for s in client.get(f'/api/v1/classes/{c["id"]}/sessions',headers=headers).json()]
    opened=client.post(f'/api/v1/sessions/{exam["id"]}/scan-session',headers=headers)
    assert opened.status_code==200, opened.text
    with factory() as db:
        qr=db.scalar(select(StudentQRCode).where(StudentQRCode.student_id==student['id']))
        qr_id=qr.id
    photo=io.BytesIO(); Image.new('RGB',(100,100),'white').save(photo,'JPEG')
    scan_ids=[]
    for side in ['OMR','OCR']:
        capture=str(uuid4())
        token=page_token(qr_id,side,0,m.settings.qr_signing_secret or m.settings.jwt_secret)
        fields={'session_id':exam['id'],'scan_session_id':opened.json()['id'],'page_token':token,'client_capture_id':capture}
        upload=lambda:client.post('/api/v1/scans',headers={**headers,'Idempotency-Key':capture}, data=fields,files={'image':('card.jpg',photo.getvalue(),'image/jpeg')})
        response=upload(); assert response.status_code==201,response.text
        scan_id=response.json()['server_scan_id'];scan_ids.append(scan_id)
        assert upload().json()['server_scan_id']==scan_id
        def recognize(image,template,page_side):
            return {'template_version':template,'page_type':page_side,'page_quality':{'status':'OK'},'answers':[{'question_no':1,'type':'CHOICE' if side=='OMR' else 'TEXT','value':'B','raw_text':'because','status':'RECOGNIZED','confidence':.99}]}
        with factory() as db:
            process_scan(db,db.get(ScanRecord,scan_id),recognize)
    results=client.get(f'/api/v1/sessions/{exam["id"]}/results',headers=headers).json()
    answers=results['students'][0]
    assert answers['answers']=={'1':'B','2':'because'}
    assert answers['status']=='REVIEW_REQUIRED' and answers['score']==1
    scans=client.get(f'/api/v1/sessions/{exam["id"]}/scans',headers=headers).json()
    assert any(s['recognition']['mapped_answers'][0]['value']=='because' for s in scans)
    assert client.post(f'/api/v1/scans/{scan_ids[1]}/review',headers=headers,json={'answers':[{'question_no':1,'value':'B'}]}).status_code==422
    reviewed=client.post(f'/api/v1/scans/{scan_ids[1]}/review',headers=headers,json={'answers':[{'question_no':2,'value':'because'}]})
    assert reviewed.status_code==200,reviewed.text
    results=client.get(f'/api/v1/sessions/{exam["id"]}/results',headers=headers).json()
    assert results['students'][0]['score']==2
    assert results['students'][0]['answers']=={'1':'B','2':'because'}
    client.post(f'/api/v1/sessions/{exam["id"]}/archive',headers=headers)
    assert client.post(f'/api/v1/sessions/{exam["id"]}/scan-session',headers=headers).status_code==409


def test_page_identity_authentication():
    token=page_token(str(uuid4()),'OCR',0,'test-secret')
    assert parse_page_token(token,'test-secret')[1:]==('OCR',0)
    assert parse_page_token(token.replace('.OCR.','.OMR.'),'test-secret') is None
    assert parse_page_token(token,'wrong-secret') is None


def test_choice_validation_and_long_text(classroom):
    client,headers,c,*_=classroom
    base={'class_id':c['id'],'question_count':1}
    bad=client.post('/api/v1/sessions',headers=headers,json={**base,'answer_keys':[{'question_no':1,'value':'wrong'}]})
    assert bad.status_code==422
    good=client.post('/api/v1/sessions',headers=headers,json={**base,'answer_keys':[{'question_no':1,'value':'文字答案'*50,'question_type':'OCR_SHORT_ANSWER'}]})
    assert good.status_code==201
