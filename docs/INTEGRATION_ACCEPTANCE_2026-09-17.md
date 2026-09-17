# 三项目 A5 答题卡集成验收

## 今日完成项目

范围为本任务实际修改的三个现有正式仓库，没有创建项目副本或 worktree。

| 项目 | 正式路径 | 分支 | 本轮功能提交 |
|---|---|---|---|
| Web/Backend | `D:\Codex\01_App-应用开发\004_ClassroomAssessmentPlatform-课堂答题平台` | feature/web-backend-v1 | d1524bc1af74972f2c08c0a1838e51a247488284 |
| Recognition | `D:\Codex\01_App-应用开发\005_ClassroomRecognitionService-课堂答题识别服务` | feature/recognition-poc | 89f0e2607cb92f07a84c3e8e26bb7a84581d21fd |
| Android | `D:\Codex\classroom-scanner-android` | feature/scanner-v1 | 6977c7aa51aac526d1ff8710eac59125cbc06139 |

`TODAY_WORKSPACE_AUDIT`：开始时三个工作树均干净。提交范围为学生卡/PDF、文字题、扫描状态规则、独立识别队列与复核、模板及 OMR 修正、Android 会话过滤与版本、部署脚本和文档。六项 Backend 测试、十一项 Recognition 测试、Recognition ruff、Alembic upgrade/check、Web build、Android 单元测试和 Debug/Release 构建通过。临时图片、PDF、SQLite、日志和 APK 留在忽略目录，未整目录提交。

### 产品入口

1. 班级 → 查看班级 → 点击学生姓名：二维码弹窗，单生 A5 下载。
2. 班级 → 批量下载答题卡：每生一组默认双面卡。
3. 新建考试 → 文字题与正确答案：逐行批量输入及分值。
4. 考试实时/结果页 → 扫描与复核：本场完整页数 PDF、原图、识别原文、重试及核验。
5. 安卓 0.3.0：进行中和已结束考试均可选择，草稿和已归档考试不能扫描。

### 验收证据

| 检查 | 结果 | 证据范围 |
|---|---|---|
| A5 PDF 排版 | PASS | 本机渲染两面，148×210 mm，右上角二维码、四角点、矩形选择框 |
| 实际 PDF + 合成填涂 | PASS | 40/40 OMR；同时发现并修复全黑框被当空白的问题 |
| 实际 PDF + 印刷文本 | PASS | 本地真实 PaddleOCR，10 个英文词；不是手写准确率 |
| 本地浏览器 | PASS | 登录、班级姓名入口、二维码、下载入口、文字题创建、原图复核、计分刷新 |
| 线上浏览器 | PASS | HTTPS 登录页正常；没有把此项写成真实教师登录验收 |
| 线上完整 HTTP | PASS | 真实 Web PDF → 二维码解码 → 结束考试 → 双面上传 → 后台消费者 → 独立 Recognition → 合并 → 核验计分 |
| 线上 OMR/OCR | PASS | 4/4 选择题、2/2 印刷英文词，使用真实 PP-OCRv5_mobile_rec |
| 幂等 | PASS | 同一 capture 重传返回相同 scan id |
| 核验计分 | PASS | 文字核验前 4 分，核验后 6 分，前面答案保留 |
| 归档约束 | PASS | 归档后 scan-session 返回 409 |
| 测试数据 | 已归档 | 仅在既有演示机构创建合成班级、学生、考试；未改密码 |
| 实纸、手写、新 APK 真机 | PENDING_REAL_DEVICE | 不能用旧版真机记录替代新版验收 |

### 测试环境部署

地址：`https://assessment.mychangliapp.cn/`。当前部署的功能提交为 `d1524bc1af74972f2c08c0a1838e51a247488284`；本报告及后续检查脚本属于后续文档/运维记录，不改变该运行代码身份。

- API、识别队列、Recognition、PostgreSQL、Nginx 均 active。
- API `127.0.0.1:8101`，Recognition `127.0.0.1:8092`，未新增公网识别端口。
- `/health`、`/ready` 和 HTTPS 通过。
- 以当前 systemd InvocationID 检查 API、Worker、Recognition 警告/错误日志，结果为空。
- `mychangliapp.cn`、`api.mychangliapp.cn/health`、`api.mychangliapp.cn/ready` 前后保护检查通过。
- 识别采用单 CPU 线程，CPUQuota 75%，MemoryHigh 700M、MemoryMax 900M。
- 扫描文件持久目录 `/opt/classroom-assessment-platform/data/scans`，独立二维码密钥跨发布保持。
- 模板两仓库及服务器 SHA-256 一致：OMR `67958f05056be0fdffe034359284202bc274beb95a2bab1b4d51139099e2dc4f`；OCR `fb3b3e35f36ac984db226df63b8d0e9ffef15df7fafebf9f8641342d13ddd0b5`。

## GitHub 归档

| 项目 | Repository | Branch | 功能 Local HEAD | 功能 Remote HEAD | Push | Tag | Release |
|---|---|---|---|---|---|---|---|
| Web/Backend | HEltDeng/classroom-assessment-platform | feature/web-backend-v1 | d1524bc | d1524bc | PASS | 未创建 | 未创建 |
| Recognition | HEltDeng/classroom-recognition-service | feature/recognition-poc | 89f0e26 | 89f0e26 | PASS | 未创建 | 未创建 |
| Android | HEltDeng/classroom-scanner-android | feature/scanner-v1 | 6977c7a | 6977c7a | PASS | 未创建 | 未创建 |

以上为功能提交的验证快照。本报告随 Web feature 分支另行提交，最终 HEAD 以 Git 和任务最终报告为准。main/stable 未更新。对话历史由 Codex 管理，不声称聊天数据库已上传。

## 正式发行物

本轮仅生成待真机验收的签名候选包，不创建正式 GitHub Release 或 Store Release。

| 版本 | 文件 | SHA-256 | GitHub Release | Download Asset |
|---|---|---|---|---|
| 0.3.0 / code 6 | classroom-scanner-android-v0.3.0-code6-release.apk，24,112,693 bytes | 345D8D2D59B6637E2251A9C81A1C823B0E7D1071311B592F1F21885FEC41C187 | 未创建 | 本地 release 目录 |

applicationId：`com.classroomassessment.scanner`。证书 SHA-256：`09653af4bbd8ec0e72c463bd1edb73a832195a1a6b3779be959a6ed9a5970546`，与本扫描器既有身份一致，未复用 MyChangLi 签名。

## 未上传项目

三个源码仓库已进入各自 feature 分支。APK、截图、合成图片、PDF 示例、测试库及模型缓存留本地，未加入 Git；APK 尚缺新版实纸真机验收，不作为正式发行物上传。

## 安全检查

Secrets uploaded: NO
Production DB uploaded: NO
Private keys uploaded: NO
Keystore uploaded: NO

## 最终结论

已验收的软件功能和三仓库源码归档通过，测试环境 Web/Backend/Recognition 部署及合成样本完整 HTTP 链路通过。新版 Android 真实打印、拍摄与手写效果待验收；正式 GitHub Release、正式生产验收、Store Release 未执行。
