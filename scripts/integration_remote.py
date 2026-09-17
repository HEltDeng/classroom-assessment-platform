"""Prepare the independent loopback recognition service using the existing SSH wrapper."""
import argparse
import io
from pathlib import Path
import tarfile
from uuid import uuid4

from deploy import Remote, shell


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--action', choices=['inspect', 'deploy', 'start', 'worker', 'verify'], required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--web-host')
    args = parser.parse_args()
    remote = Remote()
    try:
        print(remote.run('free -m; df -h /opt; python3 --version; systemctl is-active classroom-recognition.service || true'))
        if args.action == 'verify':
            target='/tmp/classroom-a5-acceptance-'+uuid4().hex
            remote.run(f'mkdir -m 700 {shell(target)}')
            for name in ['remote_acceptance.py','render_acceptance_sheet.py']:
                remote.put_bytes((args.repo/'scripts'/name).read_bytes(),target+'/'+name)
            command=f"set -a; . /etc/classroom-assessment-platform/backend.env; set +a; /opt/classroom-assessment-platform/current/backend/.venv/bin/python {shell(target+'/remote_acceptance.py')}"
            print(remote.run(command,sudo=True,timeout=360))
            return
        if args.action == 'start':
            remote.run('export DEBIAN_FRONTEND=noninteractive; apt-get install -y libgl1 libglib2.0-0', sudo=True, timeout=300)
            print(remote.run('/opt/classroom-recognition-service/.venv/bin/pip check', sudo=True))
            print(remote.run('systemctl enable --now classroom-recognition.service; systemctl restart classroom-recognition.service; systemctl is-active classroom-recognition.service', sudo=True))
            return
        if args.action == 'worker':
            print(remote.run('systemctl enable --now classroom-assessment-recognition-worker.service; systemctl restart classroom-assessment-recognition-worker.service; systemctl is-active classroom-assessment-recognition-worker.service; curl -fsS http://127.0.0.1:8092/health', sudo=True))
            return
        if args.action == 'inspect':
            print(remote.run('journalctl -u classroom-recognition.service -n 18 --no-pager -o cat', sudo=True, check=False))
            print(remote.run('tail -n 4 /opt/classroom-recognition-service/install.log; /opt/classroom-recognition-service/.venv/bin/pip show paddleocr paddlepaddle | head -n 18', sudo=True, check=False))
            return
        source = args.repo.parent / '005_ClassroomRecognitionService-课堂答题识别服务'
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w:gz') as tar:
            for folder in ['src', 'templates']:
                for path in (source / folder).rglob('*'):
                    if path.is_file() and '__pycache__' not in path.parts and path.suffix in {'.py', '.json'}:
                        tar.add(path, arcname=path.relative_to(source).as_posix())
            for name in ['pyproject.toml', 'README.md', 'LICENSE']:
                tar.add(source / name, arcname=name)
        upload = '/tmp/classroom-recognition-' + uuid4().hex
        remote.run(f'mkdir -m 700 {shell(upload)}')
        remote.put_bytes(archive.getvalue(), upload+'/code.tgz')
        root='/opt/classroom-recognition-service'
        # The existing service account is shared only for local image access;
        # recognition has no classroom credentials or database access.
        remote.run(f'install -d -o classroom-assessment -g classroom-assessment -m 750 {root} {root}/cache /opt/classroom-assessment-platform/data/scans; tar -xzf {shell(upload+"/code.tgz")} -C {root}; python3 -m venv {root}/.venv', sudo=True)
        print('Recognition source prepared; installing CPU dependencies.')
        install = f'{root}/.venv/bin/pip install --disable-pip-version-check -e {root} paddleocr==3.7.0 paddlepaddle==3.3.1'
        # Detached installation survives transport resets and is checked separately.
        remote.run(f'systemd-run --unit=classroom-recognition-setup --collect -p CPUQuota=75% /bin/sh -c {shell(install + " > " + root + "/install.log 2>&1")}', sudo=True)
        unit=f'''[Unit]
Description=Classroom independent OMR OCR recognition
After=network-online.target
[Service]
User=classroom-assessment
Group=classroom-assessment
WorkingDirectory={root}
Environment=HOME={root}/cache
Environment=PADDLEOCR_MODEL_NAME=PP-OCRv5_mobile_rec
Environment=OCR_CPU_THREADS=1
Environment=OMP_NUM_THREADS=1
Environment=OPENBLAS_NUM_THREADS=1
ExecStart={root}/.venv/bin/python -m uvicorn src.api.app:app --host 127.0.0.1 --port 8092 --no-access-log
CPUQuota=75%
MemoryHigh=700M
MemoryMax=900M
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths={root}/cache
UMask=027
[Install]
WantedBy=multi-user.target
'''
        remote.put_bytes(unit.encode(),upload+'/recognition.service')
        remote.install_remote_file(upload+'/recognition.service','/etc/systemd/system/classroom-recognition.service',mode='644',owner='root',group='root')
        remote.put_bytes((args.repo/'infra/systemd/classroom-assessment-recognition-worker.service').read_bytes(),upload+'/worker.service')
        remote.install_remote_file(upload+'/worker.service','/etc/systemd/system/classroom-assessment-recognition-worker.service',mode='644',owner='root',group='root')
        remote.run('systemctl daemon-reload',sudo=True)
        print('Units installed; activation awaits dependency and API migration checks.')
    finally:
        remote.close()


if __name__=='__main__':
    main()
