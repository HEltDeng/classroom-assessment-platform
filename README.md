# Classroom Assessment Platform

课堂答题与学情自动化系统的独立 Web + Backend 子项目。

本仓库只包含：

- `web/`：React + TypeScript + Vite 响应式课堂管理与实时大屏；
- `backend/`：FastAPI 模块化单体、认证、业务 API、SSE 实时事件；
- `docs/`：API Contract、部署和验收记录；
- `infra/`：独立 systemd、Nginx 和部署模板；
- `scripts/`：本地初始化、验收和部署辅助脚本。

Android Scanner、CameraX、二维码扫描、OMR/OCR、OpenCV、PaddleOCR 和视觉识别服务不属于本仓库。

## 本地启动

要求：Python 3.11+、Node.js 20+、Docker Desktop（用于 PostgreSQL）。

```powershell
Copy-Item .env.example .env
# 编辑 .env，设置本机 PostgreSQL 密码、JWT_SECRET 和 SEED_DEMO_PASSWORD
docker compose up -d postgres
python -m venv backend/.venv
& backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
Push-Location backend
& .\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
Pop-Location
& backend/.venv/Scripts/python.exe scripts/seed_demo.py
Push-Location web
npm install
npm run dev
Pop-Location
```

另开终端启动 API：

```powershell
& backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

演示账号用户名为 `teacher@example.com`，新账号创建时的密码必须通过本机 `.env` 中的 `SEED_DEMO_PASSWORD` 提供。该变量没有仓库内默认值；生产环境必须设置独立随机 `JWT_SECRET` 和密码。

## 验证

```powershell
& backend/.venv/Scripts/python.exe -m pytest backend/tests -q
Push-Location web
npm run build
Pop-Location
```

完整课堂闭环见 `docs/ACCEPTANCE_CHECKLIST.md`，稳定跨系统接口见 `docs/API_CONTRACT.md`。
