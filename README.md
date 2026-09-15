# Classroom Assessment Platform

面向培训机构的智慧课堂 Web + Backend 子项目：机构统一维护教师、学生主库、班级、考试和成绩，Android Scanner / Recognition 通过稳定 API 接入。

本仓库只包含：

- `web/`：React + TypeScript + Vite 响应式教师管理端；
- `backend/`：FastAPI 模块化单体、认证、业务 API、SSE 实时事件；
- `docs/`：API Contract、部署和验收记录；
- `infra/`：独立 systemd、Nginx 和部署模板；
- `scripts/`：本地初始化、验收和部署辅助脚本。

Android Scanner、CameraX、二维码扫描、OMR/OCR、OpenCV、PaddleOCR 和视觉识别服务不属于本仓库；本仓库保留 QR token、题型和 Recognition API 的扩展边界，不会因为参考视频是微信小程序而新增或改造成微信小程序。

## 当前业务边界

- `Organization` 是教师、学生主库、班级和考试的隔离边界；首次登录且尚无机构时先完成机构初始化。
- `Student` 先进入机构学生主库，后通过 `ClassEnrollment` 加入一个或多个班级。学生编号由后端机构流水号并发安全生成，例如 `YZ0001`，创建后不因转班改变。
- Excel 学生名单只要求“姓名”列，可选“学段”“备注”；上传后先预览匹配，再由教师确认复用、创建或跳过。
- `AssessmentSession` 对外统一称为 `Exam` / 考试，支持学科、进门测/随堂测/出门测/自定义测试、逐题分值和单选 OMR；题型枚举为 OCR 扩展预留。
- 周五/周六/周日、A/B/C/D 时段和机构默认学科在创建机构时初始化，之后由机构级设置 API 管理，不写死在前端。

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

本地初始化脚本会使用 `.env` 中的 `SEED_DEMO_PASSWORD` 创建一组本地验收数据；该变量没有仓库内默认值。登录统一使用“机构名称 + 教师登录名称 + 密码”，Android Scanner 与 Web 使用同一套机构成员账号。生产环境必须设置独立随机 `JWT_SECRET` 和密码，不能使用本地初始化数据作为生产账号。

## 验证

```powershell
& backend/.venv/Scripts/python.exe -m pytest backend/tests -q
Push-Location web
npm run build
Pop-Location
```

完整课堂闭环见 `docs/ACCEPTANCE_CHECKLIST.md`，稳定跨系统接口见 `docs/API_CONTRACT.md`。
