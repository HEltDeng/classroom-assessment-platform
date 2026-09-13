"""Isolated deployment helper for the classroom assessment test environment.

SSH credentials are supplied only by the local PowerShell wrapper through
process environment variables. This module never writes or prints credentials,
database passwords, JWT secrets, or the production EnvironmentFile.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
from urllib.parse import quote
from uuid import uuid4

import paramiko


SERVICE_NAME = "classroom-assessment-api.service"
SERVICE_USER = "classroom-assessment"
APP_ROOT = "/opt/classroom-assessment-platform"
CURRENT_ROOT = f"{APP_ROOT}/current"
BACKUP_ROOT = f"{APP_ROOT}/backups"
STAGING_ROOT = f"{APP_ROOT}/staging"
ENV_DIR = "/etc/classroom-assessment-platform"
ENV_FILE = f"{ENV_DIR}/backend.env"
API_PORT = 8101
HOST_PATTERN = re.compile(r"^[A-Za-z0-9.-]+$")


def shell(value: str) -> str:
    return shlex.quote(value)


def required_env(name: str) -> str:
    value = os.environ.pop(name, "")
    if not value:
        raise RuntimeError(f"Missing required deployment runtime value: {name}")
    return value


def run_local(command: list[str], cwd: Path, timeout: int = 600) -> str:
    result = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"Local command failed: {command[:3]} ({detail[-1000:]})")
    return result.stdout.strip()


def current_commit(repo: Path) -> str:
    status = run_local(["git", "status", "--porcelain", "--untracked-files=normal"], repo)
    if status:
        raise RuntimeError("Deployment requires a clean Git worktree")
    return run_local(["git", "rev-parse", "HEAD"], repo)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_release_archive(repo: Path, commit: str) -> tuple[Path, str, tempfile.TemporaryDirectory[str]]:
    dist = repo / "web" / "dist"
    if not (dist / "index.html").is_file():
        raise RuntimeError("web/dist/index.html is missing; run the production Web build first")
    temp = tempfile.TemporaryDirectory(prefix="classroom-assessment-release-")
    temp_root = Path(temp.name)
    unpacked = temp_root / "release"
    unpacked.mkdir()
    archive_bytes = subprocess.run(
        ["git", "archive", "--format=tar", commit],
        cwd=str(repo),
        capture_output=True,
        check=False,
    )
    if archive_bytes.returncode != 0:
        temp.cleanup()
        raise RuntimeError("git archive failed")
    with tarfile.open(fileobj=io.BytesIO(archive_bytes.stdout), mode="r:") as source:
        source.extractall(unpacked)
    shutil.copytree(dist, unpacked / "web" / "dist")
    output = temp_root / "release.tar.gz"
    with tarfile.open(output, mode="w:gz") as target:
        target.add(unpacked, arcname="release")
    return output, sha256_file(output), temp


class RemoteError(RuntimeError):
    pass


class Remote:
    def __init__(self) -> None:
        host = required_env("CLASSROOM_SSH_HOST")
        port = int(os.environ.pop("CLASSROOM_SSH_PORT", "22"))
        username = required_env("CLASSROOM_SSH_USER")
        identity_file = required_env("CLASSROOM_SSH_KEY")
        key_passphrase = os.environ.pop("CLASSROOM_SSH_KEY_PASSPHRASE", "")
        self.sudo_password = required_env("CLASSROOM_SSH_SUDO")
        self.username = username
        self.client = paramiko.SSHClient()
        self.client.load_system_host_keys()
        self.client.set_missing_host_key_policy(paramiko.RejectPolicy())
        self.client.connect(
            hostname=host,
            port=port,
            username=username,
            key_filename=identity_file,
            passphrase=key_passphrase or None,
            look_for_keys=False,
            allow_agent=False,
            timeout=20,
            auth_timeout=20,
            banner_timeout=20,
        )

    def close(self) -> None:
        self.client.close()
        self.sudo_password = ""

    def run(
        self,
        command: str,
        *,
        sudo: bool = False,
        input_text: str = "",
        timeout: int = 120,
        check: bool = True,
    ) -> str:
        actual = command
        if sudo:
            actual = "/usr/bin/sudo -S -p '' -- /bin/sh -c " + shell(command)
        stdin, stdout, stderr = self.client.exec_command(actual, get_pty=sudo, timeout=timeout)
        if sudo:
            stdin.write(self.sudo_password + "\n")
        if input_text:
            stdin.write(input_text)
        stdin.flush()
        output = stdout.read().decode("utf-8", errors="replace").strip()
        error = stderr.read().decode("utf-8", errors="replace").strip()
        code = stdout.channel.recv_exit_status()
        if check and code != 0:
            detail = (error or output).replace(self.sudo_password, "<redacted>")
            raise RemoteError(f"Remote command failed ({code}): {command[:220]} ({detail[-1200:]})")
        return output

    def put_bytes(self, data: bytes, remote_path: str) -> None:
        sftp = self.client.open_sftp()
        try:
            with sftp.open(remote_path, "wb") as stream:
                stream.write(data)
        finally:
            sftp.close()

    def install_bytes(self, data: bytes, destination: str, *, mode: str, owner: str, group: str) -> None:
        temporary = f"/tmp/classroom-assessment-{uuid4().hex}"
        self.put_bytes(data, temporary)
        try:
            self.run(
                f"/usr/bin/install -m {shell(mode)} -o {shell(owner)} -g {shell(group)} "
                f"{shell(temporary)} {shell(destination)}; /bin/rm -f -- {shell(temporary)}",
                sudo=True,
            )
        finally:
            self.run(f"/bin/rm -f -- {shell(temporary)}", sudo=True, check=False)


def check_protected_endpoints() -> None:
    checks = {
        "https://mychangliapp.cn/": 200,
        "https://api.mychangliapp.cn/health": 200,
    }
    for url, expected in checks.items():
        request = Request(url, headers={"User-Agent": "ClassroomAssessmentDeployment/1"})
        try:
            with urlopen(request, timeout=20) as response:
                if response.status != expected:
                    raise RuntimeError(f"Protected endpoint returned HTTP {response.status}: {url}")
        except URLError as exc:
            raise RuntimeError(f"Protected endpoint is unreachable: {url}") from exc


def inspect(remote: Remote, host: str) -> None:
    print("Remote isolation inspection")
    print(remote.run("systemctl is-active mychangli-backend", check=False) or "existing service status unavailable")
    print(f"nginx={remote.run('systemctl is-active nginx', check=False) or 'inactive'}")
    print(f"postgresql={remote.run('systemctl is-active postgresql', check=False) or 'inactive'}")
    print(f"target_service={remote.run(f'/usr/bin/systemctl is-active {shell(SERVICE_NAME)}', check=False) or 'not-installed'}")
    print(remote.run("/bin/df -h /opt /var | tail -n +1", check=False))
    print(remote.run("/usr/bin/ss -ltn 2>/dev/null | head -40", check=False))
    print(remote.run("/usr/sbin/nginx -t", sudo=True, check=False))
    print(f"web_host={host}")


def render_template(repo: Path, filename: str, replacements: dict[str, str]) -> bytes:
    template = (repo / "infra" / "nginx" / filename).read_text(encoding="utf-8")
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template.encode("utf-8")


def deploy(remote: Remote, repo: Path, commit: str, archive: Path, archive_sha: str, host: str) -> dict[str, str]:
    remote.run(
        "need=0; command -v psql >/dev/null 2>&1 || need=1; "
        "python3 -m venv --help >/dev/null 2>&1 || need=1; "
        "if [ \"$need\" -eq 1 ]; then "
        "export DEBIAN_FRONTEND=noninteractive; /usr/bin/apt-get update; "
        "/usr/bin/apt-get install -y postgresql postgresql-client python3-venv; fi; "
        "/bin/systemctl enable --now postgresql",
        sudo=True,
        timeout=900,
    )
    remote.run(
        f"if ! /usr/bin/id -u {shell(SERVICE_USER)} >/dev/null 2>&1; then "
        f"/usr/sbin/useradd --system --home-dir {shell(APP_ROOT)} --shell /usr/sbin/nologin {shell(SERVICE_USER)}; fi; "
        f"/usr/bin/install -d -m 755 -o root -g root {shell(APP_ROOT)}; "
        f"/usr/bin/install -d -m 750 -o root -g root {shell(BACKUP_ROOT)} {shell(STAGING_ROOT)} {shell(ENV_DIR)}",
        sudo=True,
    )

    upload_root = f"/tmp/classroom-assessment-upload-{uuid4().hex}"
    remote.run(f"/bin/mkdir -m 700 {shell(upload_root)}")
    remote.put_bytes(archive.read_bytes(), upload_root + "/release.tar.gz")
    remote.run(
        f"printf '%s  %s\\n' {shell(archive_sha)} release.tar.gz > {shell(upload_root + '/manifest.sha256')}; "
        f"cd {shell(upload_root)} && /usr/bin/sha256sum -c manifest.sha256"
    )

    release_id = f"{commit[:12]}-{uuid4().hex[:8]}"
    staging = f"{STAGING_ROOT}/{release_id}"
    remote.run(
        f"/usr/bin/install -d -m 755 {shell(staging)}; "
        f"/usr/bin/tar -xzf {shell(upload_root + '/release.tar.gz')} -C {shell(staging)} --strip-components=1; "
        f"/usr/bin/test -f {shell(staging + '/backend/app/main.py')}; "
        f"/usr/bin/test -f {shell(staging + '/web/dist/index.html')}; "
        f"printf '%s\\n' {shell(commit)} > {shell(staging + '/RELEASE_SHA')}",
        sudo=True,
    )
    remote.run(
        f"/usr/bin/python3 -m venv {shell(staging + '/backend/.venv')}; "
        f"{shell(staging + '/backend/.venv/bin/pip')} install --disable-pip-version-check --no-cache-dir "
        f"-r {shell(staging + '/backend/requirements.txt')}",
        sudo=True,
        timeout=900,
    )

    db_password = secrets.token_urlsafe(32)
    escaped_db_password = db_password.replace("'", "''")
    sql = (
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='classroom_assessment') THEN "
        f"CREATE ROLE classroom_assessment LOGIN PASSWORD '{escaped_db_password}'; "
        "ELSE ALTER ROLE classroom_assessment WITH LOGIN PASSWORD "
        f"'{escaped_db_password}'; END IF; END $$;\n"
        "SELECT 'CREATE DATABASE classroom_assessment OWNER classroom_assessment' "
        "WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='classroom_assessment')\\gexec\n"
        "ALTER DATABASE classroom_assessment OWNER TO classroom_assessment;\n"
    )
    remote.run(
        "/usr/sbin/runuser -u postgres -- /usr/bin/psql -v ON_ERROR_STOP=1 --dbname=postgres",
        sudo=True,
        input_text=sql,
        timeout=120,
    )

    jwt_secret = secrets.token_urlsafe(48)
    seed_password = secrets.token_urlsafe(32)
    database_url = (
        "postgresql+psycopg://classroom_assessment:"
        f"{quote(db_password, safe='')}@127.0.0.1:5432/classroom_assessment"
    )
    env_text = (
        "APP_ENV=production\n"
        f"DATABASE_URL={database_url}\n"
        f"WEB_BASE_URL=https://{host}\n"
        f"API_BASE_URL=https://{host}/api/v1\n"
        f"JWT_SECRET={jwt_secret}\n"
        "ACCESS_TOKEN_EXPIRE_MINUTES=480\n"
        "ALLOW_DEV_SUBMISSION=false\n"
        f"SEED_DEMO_PASSWORD={seed_password}\n"
    ).encode("utf-8")
    remote.install_bytes(env_text, ENV_FILE, mode="640", owner="root", group=SERVICE_USER)
    remote.run(
        f"cd {shell(staging + '/backend')}; set -a; . {shell(ENV_FILE)}; set +a; "
        f"{shell(staging + '/backend/.venv/bin/alembic')} upgrade head; "
        f"{shell(staging + '/backend/.venv/bin/python')} {shell(staging + '/scripts/seed_demo.py')}",
        sudo=True,
        timeout=300,
    )
    remote.run(
        f"/usr/bin/chown -R {shell(SERVICE_USER + ':' + SERVICE_USER)} {shell(staging)}; "
        f"/usr/bin/chown -R root:www-data {shell(staging + '/web/dist')}; "
        f"/usr/bin/find {shell(staging + '/web/dist')} -type d -exec /bin/chmod 755 {{}} +; "
        f"/usr/bin/find {shell(staging + '/web/dist')} -type f -exec /bin/chmod 644 {{}} +",
        sudo=True,
    )

    backup_path = f"{BACKUP_ROOT}/{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{commit[:12]}"
    had_current = remote.run(f"test -e {shell(CURRENT_ROOT)}", sudo=True, check=False) == ""
    # `test` emits no output for either result, so use an explicit marker.
    had_current = remote.run(
        f"if test -e {shell(CURRENT_ROOT)}; then echo yes; else echo no; fi", sudo=True
    ) == "yes"
    if had_current:
        remote.run(f"/bin/mv -- {shell(CURRENT_ROOT)} {shell(backup_path)}", sudo=True)
    remote.run(f"/bin/mv -- {shell(staging)} {shell(CURRENT_ROOT)}", sudo=True)

    try:
        unit = (repo / "infra" / "systemd" / "classroom-assessment-api.service").read_bytes()
        remote.install_bytes(unit, f"/etc/systemd/system/{SERVICE_NAME}", mode="644", owner="root", group="root")
        remote.run(
            f"/bin/systemctl daemon-reload; /bin/systemctl enable {shell(SERVICE_NAME)}; "
            f"/bin/systemctl restart {shell(SERVICE_NAME)}; /bin/systemctl is-active {shell(SERVICE_NAME)}",
            sudo=True,
            timeout=120,
        )
        remote.run(
            "/usr/bin/curl --fail --silent --show-error http://127.0.0.1:8101/health; "
            "/usr/bin/curl --fail --silent --show-error http://127.0.0.1:8101/ready",
            sudo=True,
            timeout=60,
        )
    except Exception:
        remote.run(f"/bin/systemctl stop {shell(SERVICE_NAME)}", sudo=True, check=False)
        if had_current:
            remote.run(f"/bin/mv -- {shell(CURRENT_ROOT)} {shell(APP_ROOT + '/failed-' + release_id)}", sudo=True, check=False)
            remote.run(f"/bin/mv -- {shell(backup_path)} {shell(CURRENT_ROOT)}", sudo=True, check=False)
            remote.run(f"/bin/systemctl start {shell(SERVICE_NAME)}", sudo=True, check=False)
        raise

    web_root = f"{CURRENT_ROOT}/web/dist"
    http_config = render_template(repo, "classroom-assessment-http.conf", {
        "__WEB_HOST__": host,
        "__WEB_ROOT__": web_root,
    })
    config_path = "/etc/nginx/sites-available/classroom-assessment"
    link_path = "/etc/nginx/sites-enabled/classroom-assessment"
    remote.install_bytes(http_config, config_path, mode="644", owner="root", group="root")
    remote.run(f"/bin/ln -sfn {shell(config_path)} {shell(link_path)}; /usr/sbin/nginx -t; /bin/systemctl reload nginx", sudo=True, timeout=120)

    https_status = "PENDING_CERTIFICATE"
    try:
        remote.run(
            "if ! command -v certbot >/dev/null 2>&1; then "
            "export DEBIAN_FRONTEND=noninteractive; /usr/bin/apt-get update; "
            "/usr/bin/apt-get install -y certbot; fi",
            sudo=True,
            timeout=900,
        )
        remote.run(
            f"/usr/bin/certbot certonly --webroot --webroot-path {shell(web_root)} "
            f"--domain {shell(host)} --non-interactive --agree-tos "
            "--register-unsafely-without-email --keep-until-expiring",
            sudo=True,
            timeout=300,
        )
        cert = f"/etc/letsencrypt/live/{host}/fullchain.pem"
        key = f"/etc/letsencrypt/live/{host}/privkey.pem"
        remote.run(f"/usr/bin/test -s {shell(cert)}; /usr/bin/test -s {shell(key)}", sudo=True)
        https_config = render_template(repo, "classroom-assessment-https.conf", {
            "__WEB_HOST__": host,
            "__WEB_ROOT__": web_root,
            "__TLS_CERT__": cert,
            "__TLS_KEY__": key,
        })
        remote.install_bytes(https_config, config_path, mode="644", owner="root", group="root")
        remote.run(f"/usr/sbin/nginx -t; /bin/systemctl reload nginx", sudo=True, timeout=120)
        https_status = "PASS"
    except Exception:
        # Keep the service and HTTP site available for diagnosis. Do not turn
        # an unverified certificate into a false HTTPS success.
        https_status = "PENDING_CERTIFICATE"

    remote.run("systemctl is-active mychangli-backend", check=True)
    remote.run("/usr/sbin/nginx -t", sudo=True)
    remote.run(f"/bin/rm -rf -- {shell(upload_root)}", sudo=True, check=False)
    db_password = ""
    jwt_secret = ""
    seed_password = ""
    return {
        "release_sha": commit,
        "archive_sha256": archive_sha,
        "service": "active",
        "postgresql": remote.run("systemctl is-active postgresql", check=False) or "unknown",
        "https": https_status,
        "web_host": host,
        "protected_endpoints": "verified-before-and-after",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy the isolated classroom assessment platform")
    parser.add_argument("--action", choices=("inspect", "deploy"), required=True)
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--web-host", default=os.environ.get("CLASSROOM_WEB_HOST", "assessment.mychangliapp.cn"))
    args = parser.parse_args()
    if not HOST_PATTERN.fullmatch(args.web_host):
        raise RuntimeError("Web host contains unsupported characters")
    repo = Path(args.repo).resolve()
    if not (repo / ".git").is_dir():
        raise RuntimeError(f"Git repository is missing: {repo}")

    remote = Remote()
    try:
        if args.action == "inspect":
            inspect(remote, args.web_host)
            print("Remote inspection: PASS")
            return 0
        check_protected_endpoints()
        commit = current_commit(repo)
        archive, archive_sha, temporary = make_release_archive(repo, commit)
        try:
            result = deploy(remote, repo, commit, archive, archive_sha, args.web_host)
        finally:
            temporary.cleanup()
        print("Classroom assessment deployment: PASS")
        for key, value in result.items():
            print(f"{key}={value}")
        return 0
    finally:
        remote.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # keep credential-adjacent details out of output
        print(f"Classroom assessment deployment failed: {exc}")
        raise SystemExit(1)
