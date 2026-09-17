"""HTTP integration acceptance in the established demo institution only.

Uses a short-lived token for its existing administrator, without changing any
password or account. All created students/classes are synthetic and archived.
"""
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import httpx
from sqlalchemy import select

sys.path.insert(0, '/opt/classroom-assessment-platform/current/backend')
from app.db import SessionLocal
from app.models import Organization, OrganizationMember, MemberRole, StudentQRCode
from app.security import create_access_token
from app.answer_sheets import page_token
from app.config import get_settings


def main():
    settings = get_settings()
    root = Path(__file__).parent
    with SessionLocal() as db:
        member = db.scalar(select(OrganizationMember).join(Organization).where(Organization.name == '演示课堂机构', OrganizationMember.role == MemberRole.OWNER))
        if member is None:
            raise RuntimeError('Established demonstration institution not found')
        token = create_access_token(member.user_id, member.organization_id, member.id, member.role.value)
    client = httpx.Client(base_url='http://127.0.0.1:8101/api/v1', headers={'Authorization': 'Bearer '+token}, timeout=120)
    def call(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        return response
    classroom = call('POST', '/classes', json={'name':'A5集成验收-'+uuid4().hex[:6]}).json()
    call('POST', f'/classes/{classroom["id"]}/students', json={'students':[{'name':'A5合成测试学生'}]})
    student = call('GET',f'/classes/{classroom["id"]}').json()['students'][0]
    keys = [{'question_no':i+1,'value':value} for i,value in enumerate('ABCD')]
    keys += [{'question_no':5,'value':'because','question_type':'OCR_SHORT_ANSWER'},{'question_no':6,'value':'environment','question_type':'OCR_SHORT_ANSWER'}]
    exam = call('POST','/sessions',json={'class_id':classroom['id'],'name':'A5完整HTTP链路验收','question_count':6,'answer_keys':keys}).json()
    exam_id=exam['id']
    call('POST',f'/sessions/{exam_id}/start')
    call('POST',f'/sessions/{exam_id}/close')
    opened=call('POST',f'/sessions/{exam_id}/scan-session').json()
    available=call('GET',f'/classes/{classroom["id"]}/sessions').json()
    assert any(s['id']==exam_id for s in available)
    pdf=call('GET',f'/sessions/{exam_id}/answer-sheets.pdf').content
    (root/'sample.pdf').write_bytes(pdf)
    subprocess.run(['/opt/classroom-recognition-service/.venv/bin/python',str(root/'render_acceptance_sheet.py'),str(root/'sample.pdf'),'/opt/classroom-recognition-service/templates'],check=True)
    with SessionLocal() as db:
        qr=db.scalar(select(StudentQRCode).where(StudentQRCode.student_id==student['id']))
        qr_id=qr.id
    ids=[]
    for side in ['OMR','OCR']:
        capture=str(uuid4())
        fields={'session_id':exam_id,'scan_session_id':opened['id'],'client_capture_id':capture,'page_token':page_token(qr_id,side,0,settings.qr_signing_secret or settings.jwt_secret)}
        data=(root/f'filled-{side}.jpg').read_bytes()
        scan=call('POST','/scans',data=fields,files={'image':('page.jpg',data,'image/jpeg')},headers={'Idempotency-Key':capture}).json()
        duplicate=call('POST','/scans',data=fields,files={'image':('page.jpg',data,'image/jpeg')},headers={'Idempotency-Key':capture}).json()
        assert scan['server_scan_id']==duplicate['server_scan_id']
        ids.append(scan['server_scan_id'])
    deadline=time.monotonic()+240
    while time.monotonic()<deadline:
        scans=call('GET',f'/sessions/{exam_id}/scans').json()
        if len(scans)==2 and all(s['status']!='PROCESSING' for s in scans):
            break
        time.sleep(2)
    assert [call('GET',f'/scans/{i}').json()['status'] for i in ids]==['SUCCESS','REVIEW_REQUIRED'], 'Unexpected recognition state'
    results=call('GET',f'/sessions/{exam_id}/results').json()
    assert results['students'][0]['answers']=={'1':'A','2':'B','3':'C','4':'D','5':'because','6':'environment'}, results['students'][0]['answers']
    assert results['students'][0]['score']==4
    call('POST',f'/scans/{ids[1]}/review',json={'answers':[{'question_no':5,'value':'because'},{'question_no':6,'value':'environment'}]})
    results=call('GET',f'/sessions/{exam_id}/results').json()
    assert results['students'][0]['score']==6 and results['review_required_count']==0
    assert call('GET',f'/scans/{ids[0]}/image').content.startswith(b'\xff\xd8')
    call('POST',f'/sessions/{exam_id}/archive')
    assert client.post(f'/sessions/{exam_id}/scan-session').status_code==409
    call('PATCH',f'/classes/{classroom["id"]}',json={'status':'ARCHIVED'})
    call('PATCH',f'/students/{student["id"]}',json={'status':'INACTIVE'})
    print(json.dumps({'result':'PASS','closed_exam_scan':'PASS','actual_pdf_qr_decode':'PASS','OMR':'4/4','OCR_printed':'2/2','duplex_merge':'PASS','idempotency':'PASS','review_score':'4 -> 6','archive_rejection':'PASS','synthetic_test_data':'archived','real_print_handwriting':'PENDING_REAL_DEVICE'},ensure_ascii=False))


if __name__=='__main__':
    main()
