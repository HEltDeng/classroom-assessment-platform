# V1 验收清单

更新时间：2026-09-13（Asia/Singapore）

## 本地自动化

| 项目 | 状态 | 证据 |
| --- | --- | --- |
| Alembic migration 从空库升级 | PASS | `backend/alembic` 升级至 head |
| Backend 单元/集成流程 | PASS | `backend/.venv/Scripts/python.exe -m pytest -q`：1 passed |
| Alembic schema drift 检查 | PASS | `alembic check`：No new upgrade operations detected |
| FastAPI health/readiness | PASS | `/health`、`/ready` 均返回成功 |
| OpenAPI 交接接口 | PASS | 已验证 class students、Active filter、recognition-results 路径存在 |
| Web TypeScript/生产构建 | PASS | `pnpm run build` 成功 |
| Web 控制台级 UI | PASS | 登录、组织、班级、学生管理、课堂创建、结果页 |

## 真实浏览器闭环

| 场景 | 状态 | 证据 |
| --- | --- | --- |
| 创建机构 | PASS | 浏览器创建“自动化验收机构”并切换 |
| 创建班级与学生 | PASS | 创建两个班级，单个添加与批量添加学生 |
| 移出、重新加入、调班 | PASS | UI 确认框实际执行；历史关系保留 |
| 手机尺寸创建课堂 | PASS | 390×844 viewport；录入 5 题答案并开始 |
| 实时提交状态 | PASS | 张三灰色未提交 → 绿色已提交；后续学生更新 |
| 待复核状态 | PASS | 李四标记后显示橙色/待复核，汇总同步 |
| ABCD 分布与正确率 | PASS | 3 人提交后每题计数与 66.7% 正确率可见 |
| 选项展开姓名 | PASS | 点击正确选项显示张三，再次点击收起 |
| SSE | PASS | 页面显示“实时连接中”，提交后页面无刷新自动更新 |
| 结束课堂 | PASS | API 拒绝结束后的新提交，入口关闭 |
| 历史结果 | PASS | 结果页显示学生状态、逐题答案与课堂记录 |

## 部署验收边界

| 表面 | 状态 |
| --- | --- |
| 独立 systemd 服务/端口/EnvironmentFile | PASS；`classroom-assessment-api.service` active，127.0.0.1:8101，独立 EnvironmentFile |
| 独立 PostgreSQL 数据库与用户 | PASS；PostgreSQL active，`classroom_assessment` database/role |
| 新子域名 HTTP | PASS；Nginx HTTP → HTTPS 301，服务器直连验证 |
| 新子域名可信 HTTPS 证书 | PASS；Let's Encrypt 签发，证书校验握手通过 |
| 原有站点与 API 不受影响 | PASS；部署前后 `mychangliapp.cn`、`api.mychangliapp.cn/health`、`/ready` 均 200 |
| 真实老师账号 | PASS；线上测试账号登录 API、`/api/v1/me`、刷新保持登录及 Dashboard/机构/班级/学生/课堂记录页面已验证（2026-09-13） |
| Android 真机调用 | PENDING_REAL_DEVICE；本对话不开发 Android |
| Recognition Service 真链路 | PENDING_REAL_SERVICE；本对话只提供标准化接口 |
