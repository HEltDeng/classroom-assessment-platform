"""Isolated deployment helper for the classroom assessment test environment.

SSH credentials are supplied only by the local PowerShell wrapper through
process environment variables. This module never writes or prints credentials,
database passwords, JWT secrets, or the production EnvironmentFile.
"""

from __future__ import annotations

import argparse
import base64
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
        self.host = required_env("CLASSROOM_SSH_HOST")
        self.port = int(os.environ.pop("CLASSROOM_SSH_PORT", "22"))
        self.username = required_env("CLASSROOM_SSH_USER")
        self.identity_file = required_env("CLASSROOM_SSH_KEY")
        self.key_passphrase = os.environ.pop("CLASSROOM_SSH_KEY_PASSPHRASE", "")
        self.sudo_password = required_env("CLASSROOM_SSH_SUDO")
        self.client: paramiko.SSHClient | None = None
        self._connect()

    def _connect(self) -> None:
        self.client = paramiko.SSHClient()
        self.client.load_system_host_keys()
        self.client.set_missing_host_key_policy(paramiko.RejectPolicy())
        self.client.connect(
            hostname=self.host,
            port=self.port,
            username=self.username,
            key_filename=self.identity_file,
            passphrase=self.key_passphrase or None,
            look_for_keys=False,
            allow_agent=False,
            timeout=20,
            auth_timeout=20,
            banner_timeout=20,
        )

    def reconnect(self) -> None:
        if self.client is not None:
            self.client.close()
        self._connect()

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
        self.sudo_password = ""
        self.key_passphrase = ""

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
            sudo_command = "/usr/bin/sudo -S -p '' -- /bin/sh -c " + shell(command)
            # The PTY is required by sudo on this host, but its default echo
            # mode would reveal the password written to stdin. Disable echo
            # for the credential exchange and restore it before the channel
            # exits.
            actual = (
                "/bin/stty -echo 2>/dev/null; "
                + sudo_command
                + "; status=$?; /bin/stty echo 2>/dev/null; exit $status"
            )
        if self.client is None:
            raise RemoteError("Remote connection is closed")
        stdin, stdout, stderr = self.client.exec_command(actual, get_pty=sudo, timeout=timeout)
        if sudo:
            stdin.write(self.sudo_password + "\n")
        if input_text:
            stdin.write(input_text)
        stdin.flush()
        stdin.channel.shutdown_write()
        output = stdout.read().decode("utf-8", errors="replace").strip()
        error = stderr.read().decode("utf-8", errors="replace").strip()
        code = stdout.channel.recv_exit_status()
        stdin.close()
        stdout.close()
        stderr.close()
        stdout.channel.close()
        if check and code != 0:
            detail = (error or output).replace(self.sudo_password, "<redacted>")
            raise RemoteError(f"Remote command failed ({code}): {command[:220]} ({detail[-1200:]})")
        return output

    def put_bytes(self, data: bytes, remote_path: str) -> None:
        # The server's SFTP subsystem can drop larger writes. Stream a
        # base64 payload through a normal SSH channel instead, then verify
        # the archive hash in the caller before extracting it.
        if self.client is None:
            raise RemoteError("Remote connection is closed")
        stdin, stdout, stderr = self.client.exec_command(
            f"umask 077; /usr/bin/base64 --decode > {shell(remote_path)}", timeout=180
        )
        stdin.write(base64.b64encode(data).decode("ascii"))
        stdin.flush()
        stdin.channel.shutdown_write()
        error = stderr.read().decode("utf-8", errors="replace").strip()
        code = stdout.channel.recv_exit_status()
        if code != 0:
            raise RemoteError(f"Remote upload failed ({code}): {error[-600:]}")

    def install_remote_file(self, source: str, destination: str, *, mode: str, owner: str, group: str) -> None:
        self.run(
            f"/usr/bin/install -m {shell(mode)} -o {shell(owner)} -g {shell(group)} "
            f"{shell(source)} {shell(destination)}",
            sudo=True,
        )


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
    print(remote.run(f"/usr/bin/systemctl status {shell(SERVICE_NAME)} --no-pager -l", sudo=True, check=False))
    print(remote.run(f"/usr/bin/journalctl -u {shell(SERVICE_NAME)} --since '-30 min' --no-pager -n 80", sudo=True, check=False))
    print(remote.run(
        f"/usr/bin/readlink -f {shell(CURRENT_ROOT)} 2>/dev/null || true; "
        f"/usr/bin/stat -c '%A %U:%G %n' {shell(ENV_FILE)} 2>/dev/null || true",
        sudo=True,
        check=False,
    ))
    print(remote.run(
        "if command -v certbot >/dev/null 2>&1; then "
        "/usr/bin/certbot certificates 2>&1; "
        "fi",
        sudo=True,
        check=False,
    ))
    print(remote.run(
        "if test -f /var/log/letsencrypt/letsencrypt.log; then "
        "/usr/bin/grep -Ei 'error|failed|challenge|dns|assessment' /var/log/letsencrypt/letsencrypt.log | /usr/bin/tail -n 40; "
        "fi",
        sudo=True,
        check=False,
    ))
    print(remote.run("/bin/df -h /opt /var | tail -n +1", check=False))
    print(remote.run("/usr/bin/ss -ltn 2>/dev/null | head -40", check=False))
    print(remote.run("/usr/sbin/nginx -t", sudo=True, check=False))
    print(f"web_host={host}")


def render_template(repo: Path, filename: str, replacements: dict[str, str]) -> bytes:
    template = (repo / "infra" / "nginx" / filename).read_text(encoding="utf-8")
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template.encode("utf-8")


def deploy_v2(remote: Remote, repo: Path, commit: str, archive: Path, archive_sha: str, host: str) -> dict[str, str]:
    """Deploy one release without feeding privileged commands through stdin.

    The target host can reset SSH transports during apt/systemd operations.
    Uploading the archive, SQL, environment, systemd unit, and Nginx templates
    before the first privileged operation makes the sequence restartable. SQL
    is executed with ``psql --file`` because sudo allocates a PTY and direct
    psql stdin can otherwise wait for an EOF that never arrives.
    """
    release_id = f"{commit[:12]}-{uuid4().hex[:8]}"
    staging = f"{STAGING_ROOT}/{release_id}"
    upload_root = f"/tmp/classroom-assessment-upload-{uuid4().hex}"
    web_root = f"{CURRENT_ROOT}/web/dist"
    config_path = "/etc/nginx/sites-available/classroom-assessment"
    link_path = "/etc/nginx/sites-enabled/classroom-assessment"

    db_password = secrets.token_urlsafe(32)
    escaped_db_password = db_password.replace("'", "''")
    db_sql = (
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='classroom_assessment') THEN "
        f"CREATE ROLE classroom_assessment LOGIN PASSWORD '{escaped_db_password}'; "
        "ELSE ALTER ROLE classroom_assessment WITH LOGIN PASSWORD "
        f"'{escaped_db_password}'; END IF; END $$;\n"
        "SELECT 'CREATE DATABASE classroom_assessment OWNER classroom_assessment' "
        "WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='classroom_assessment')\\gexec\n"
        "ALTER DATABASE classroom_assessment OWNER TO classroom_assessment;\n"
    ).encode("utf-8")

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

    unit = (repo / "infra" / "systemd" / "classroom-assessment-api.service").read_bytes()
    http_config = render_template(repo, "classroom-assessment-http.conf", {
        "__WEB_HOST__": host,
        "__WEB_ROOT__": web_root,
    })
    cert = f"/etc/letsencrypt/live/{host}/fullchain.pem"
    key = f"/etc/letsencrypt/live/{host}/privkey.pem"
    https_config = render_template(repo, "classroom-assessment-https.conf", {
        "__WEB_HOST__": host,
        "__WEB_ROOT__": web_root,
        "__TLS_CERT__": cert,
        "__TLS_KEY__": key,
    })

    # Remove only temporary files created by this deployment helper. This is
    # intentionally narrower than a general /tmp cleanup and also removes
    # secret-bearing artifacts left by an interrupted earlier attempt.
    remote.run(
        "for path in /tmp/classroom-assessment-upload-*; do "
        "if test -d \"$path\"; then /bin/rm -rf -- \"$path\"; fi; done; "
        "for path in /tmp/classroom-assessment-db-*.sql; do "
        "if test -f \"$path\"; then /bin/rm -f -- \"$path\"; fi; done",
        sudo=True,
    )
    remote.reconnect()

    # Keep temporary files private. put_bytes applies umask 077 to every file.
    remote.run(f"/bin/mkdir -m 700 {shell(upload_root)}")
    remote.put_bytes(archive.read_bytes(), upload_root + "/release.tar.gz")
    remote.put_bytes(db_sql, upload_root + "/db.sql")
    remote.put_bytes(env_text, upload_root + "/backend.env")
    remote.put_bytes(unit, upload_root + "/classroom-assessment-api.service")
    remote.put_bytes(http_config, upload_root + "/classroom-assessment-http.conf")
    remote.put_bytes(https_config, upload_root + "/classroom-assessment-https.conf")
    remote.run(
        f"printf '%s  %s\\n' {shell(archive_sha)} release.tar.gz > {shell(upload_root + '/manifest.sha256')}; "
        f"cd {shell(upload_root)} && /usr/bin/sha256sum -c manifest.sha256"
    )

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

    # apt/systemctl may invalidate the Paramiko transport.
    remote.reconnect()
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
    # Snapshot every rollback input before replacing the live EnvironmentFile
    # or running migrations. The database dump is created by the local
    # postgres peer account and then installed into the root-owned backup
    # directory, so no database password is ever printed or stored in the
    # deployment package.
    predeploy_backup_path = (
        f"{BACKUP_ROOT}/predeploy-"
        f"{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-"
        f"{uuid4().hex[:8]}"
    )
    db_backup_tmp = f"/tmp/classroom-assessment-predeploy-db-{uuid4().hex}.dump"
    remote.run(
        "set -eu; "
        f"/usr/bin/install -d -m 750 -o root -g root {shell(predeploy_backup_path)}; "
        f"if test -e {shell(CURRENT_ROOT)}; then "
        f"/bin/cp -a -- {shell(CURRENT_ROOT)} {shell(predeploy_backup_path + '/release')}; "
        "fi; "
        f"if test -f {shell(ENV_FILE)}; then "
        f"/usr/bin/install -m 640 -o root -g root {shell(ENV_FILE)} "
        f"{shell(predeploy_backup_path + '/backend.env')}; "
        "fi; "
        f"if test -e {shell(link_path)}; then "
        f"/bin/cp -aL -- {shell(link_path)} "
        f"{shell(predeploy_backup_path + '/classroom-assessment.nginx')}; "
        "fi; "
        f"if test -f {shell(CURRENT_ROOT + '/RELEASE_SHA')}; then "
        f"/bin/cp -- {shell(CURRENT_ROOT + '/RELEASE_SHA')} "
        f"{shell(predeploy_backup_path + '/PRE_DEPLOY_COMMIT')}; "
        "else "
        f"/bin/printf '%s\\n' unknown > {shell(predeploy_backup_path + '/PRE_DEPLOY_COMMIT')}; "
        "fi; "
        f"trap '/bin/rm -f -- {shell(db_backup_tmp)}' EXIT; "
        f"/usr/sbin/runuser -u postgres -- /usr/bin/pg_dump --format=custom "
        f"--file {shell(db_backup_tmp)} classroom_assessment; "
        f"/usr/bin/install -m 640 -o root -g root {shell(db_backup_tmp)} "
        f"{shell(predeploy_backup_path + '/classroom_assessment.pg_dump')}; "
        f"/usr/bin/sha256sum {shell(predeploy_backup_path + '/classroom_assessment.pg_dump')} "
        f"> {shell(predeploy_backup_path + '/MANIFEST.sha256')}",
        sudo=True,
        timeout=300,
    )
    remote.install_remote_file(
        upload_root + "/backend.env",
        ENV_FILE,
        mode="640",
        owner="root",
        group=SERVICE_USER,
    )
    db_sql_path = f"/tmp/classroom-assessment-db-{uuid4().hex}.sql"
    remote.install_remote_file(
        upload_root + "/db.sql",
        db_sql_path,
        mode="640",
        owner="root",
        group="postgres",
    )
    try:
        remote.run(
            f"/usr/sbin/runuser -u postgres -- /usr/bin/psql -v ON_ERROR_STOP=1 "
            f"--dbname=postgres --file {shell(db_sql_path)}",
            sudo=True,
            timeout=120,
        )
    finally:
        remote.run(f"/bin/rm -f -- {shell(db_sql_path)}", sudo=True, check=False)
    remote.run(
        f"set -eu; cd {shell(staging + '/backend')}; set -a; . {shell(ENV_FILE)}; set +a; "
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

    release_backup_path = f"{BACKUP_ROOT}/{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{commit[:12]}"
    had_current = remote.run(
        f"if test -e {shell(CURRENT_ROOT)}; then echo yes; else echo no; fi", sudo=True
    ) == "yes"
    if had_current:
        remote.run(f"/bin/mv -- {shell(CURRENT_ROOT)} {shell(release_backup_path)}", sudo=True)
    remote.run(f"/bin/mv -- {shell(staging)} {shell(CURRENT_ROOT)}", sudo=True)

    try:
        remote.install_remote_file(
            upload_root + "/classroom-assessment-api.service",
            f"/etc/systemd/system/{SERVICE_NAME}",
            mode="644",
            owner="root",
            group="root",
        )
        remote.run(
            f"/bin/systemctl daemon-reload; /bin/systemctl enable {shell(SERVICE_NAME)}; "
            f"/bin/systemctl restart {shell(SERVICE_NAME)}; /bin/systemctl is-active {shell(SERVICE_NAME)}",
            sudo=True,
            timeout=120,
        )
        remote.run(
            "/usr/bin/curl --fail --silent --show-error --retry 30 --retry-delay 1 "
            "--retry-connrefused http://127.0.0.1:8101/health; "
            "/usr/bin/curl --fail --silent --show-error http://127.0.0.1:8101/ready",
            sudo=True,
            timeout=60,
        )
    except Exception:
        remote.run(f"/bin/systemctl stop {shell(SERVICE_NAME)}", sudo=True, check=False)
        failed_path = APP_ROOT + "/failed-" + release_id
        remote.run(
            f"if test -e {shell(CURRENT_ROOT)}; then /bin/mv -- {shell(CURRENT_ROOT)} {shell(failed_path)}; fi",
            sudo=True,
            check=False,
        )
        if had_current:
            remote.run(f"/bin/mv -- {shell(release_backup_path)} {shell(CURRENT_ROOT)}", sudo=True, check=False)
            remote.run(f"/bin/systemctl start {shell(SERVICE_NAME)}", sudo=True, check=False)
        raise

    remote.install_remote_file(
        upload_root + "/classroom-assessment-http.conf",
        config_path,
        mode="644",
        owner="root",
        group="root",
    )
    remote.run(
        f"/bin/ln -sfn {shell(config_path)} {shell(link_path)}; "
        f"/usr/sbin/nginx -t; /bin/systemctl reload nginx",
        sudo=True,
        timeout=120,
    )

    https_status = "PENDING_CERTIFICATE"
    try:
        remote.run(
            "if ! command -v certbot >/dev/null 2>&1; then "
            "export DEBIAN_FRONTEND=noninteractive; /usr/bin/apt-get update; "
            "/usr/bin/apt-get install -y certbot; fi",
            sudo=True,
            timeout=900,
        )
        remote.reconnect()
        remote.run(
            f"/usr/bin/certbot certonly --webroot --webroot-path {shell(web_root)} "
            f"--domain {shell(host)} --non-interactive --agree-tos "
            "--register-unsafely-without-email --keep-until-expiring",
            sudo=True,
            timeout=300,
        )
        remote.run(f"/usr/bin/test -s {shell(cert)}; /usr/bin/test -s {shell(key)}", sudo=True)
        remote.install_remote_file(
            upload_root + "/classroom-assessment-https.conf",
            config_path,
            mode="644",
            owner="root",
            group="root",
        )
        remote.run(f"/usr/sbin/nginx -t; /bin/systemctl reload nginx", sudo=True, timeout=120)
        https_status = "PASS"
    except Exception:
        # Keep the service and HTTP site available for diagnosis. Do not turn
        # an unverified certificate into a false HTTPS success.
        https_status = "PENDING_CERTIFICATE"

    remote.run("systemctl is-active mychangli-backend", check=True)
    remote.run("/usr/sbin/nginx -t", sudo=True)
    remote.run(f"/bin/rm -rf -- {shell(upload_root)}", sudo=True, check=False)
    return {
        "release_sha": commit,
        "archive_sha256": archive_sha,
        "predeploy_backup": predeploy_backup_path,
        "rollback_release": release_backup_path if had_current else "none",
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
            result = deploy_v2(remote, repo, commit, archive, archive_sha, args.web_host)
            check_protected_endpoints()
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
