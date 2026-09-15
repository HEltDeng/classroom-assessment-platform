# Classroom Assessment Platform API Contract

版本：`v1`
适用范围：Web、Android Scanner 和 Recognition Service 之间的稳定业务边界。

本合同只描述标准 HTTP/SSE 数据，不依赖 Android、CameraX、OpenCV、PaddleOCR 或任何具体识别引擎。

## 1. Base URL 与认证

客户端从部署环境读取：

```text
WEB_BASE_URL
API_BASE_URL
```

本地开发默认：

```text
WEB_BASE_URL=http://localhost:5173
API_BASE_URL=http://localhost:8000/api/v1
```

生产环境使用同源 Web 地址作为 `WEB_BASE_URL`，API 地址指向同一站点的 `/api/v1` 路径。不要在客户端写死域名。

当前测试环境示例：

```text
WEB_BASE_URL=https://assessment.mychangliapp.cn
API_BASE_URL=https://assessment.mychangliapp.cn/api/v1
```

除登录和系统健康检查外，接口使用：

```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

登录签发的 JWT 固定包含 `user_id`、`organization_id`、`teacher_id` 和 `role`。组织上下文由签名会话确定，客户端不能通过请求头切换机构。

登录：

```http
POST /api/v1/auth/login
```

```json
{
  "organization_name": "叶芝",
  "teacher_login_name": "rodush",
  "password": "<password>"
}
```

成功响应：

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "user": {"id": "...", "email": "...", "display_name": "..."},
  "organization_id": "...",
  "organization_name": "叶芝",
  "teacher_id": "...",
  "teacher_name": "Rodush",
  "login_name": "rodush",
  "role": "OWNER"
}
```

SSE 原生 `EventSource` 无法设置 Authorization header，因此 `/stream` 同时接受短期 Bearer 查询参数：

```text
GET /api/v1/sessions/{session_id}/stream?access_token=<jwt>
```

不要把 SSE URL 写入日志或持久化到业务数据。

## 2. 核心资源

| 资源 | 说明 |
| --- | --- |
| Organization / OrganizationSettings | 多机构隔离、机构代码前缀和展示配置 |
| User / OrganizationMember | 登录用户与 OWNER/ADMIN/TEACHER 角色 |
| Subject / CourseDay / TimeSlot | 机构级学科、上课日和可配置上课时段 |
| Class | 组织内班级，绑定教师、学段、上课日和时段 |
| Student | 机构学生主库；`organization_id + student_code` 唯一且编号不可变 |
| ClassEnrollment | 学生进出班级的历史关系；移出/转班不删除 Student |
| StudentQRCode | 学生固定二维码 token 的哈希、版本和撤销状态 |
| AssessmentSession | 一场班级考试（API 保留 session 命名以兼容旧 Scanner） |
| SessionParticipant | 创建考试时的班级名单快照 |
| Question / AnswerKey | 题型、分值和标准答案；当前完整实现单选 OMR |
| Submission / StudentAnswer | 学生当前有效答题结果、得分和逐题答案 |
| ScannerSession | 当前教师针对一场 Web 测试的现场扫描操作会话 |
| ScanRecord | 机构隔离的图片接收回执、幂等键和识别状态 |

考试状态：`DRAFT`、`ACTIVE`、`CLOSED`、`ARCHIVED`。

学段：`PRIMARY`、`MIDDLE`、`HIGH`。考试类型：`ENTRY`、`IN_CLASS`、`EXIT`、`CUSTOM`。
学生状态：`ACTIVE`、`INACTIVE`；结果状态：`PENDING`、`SUBMITTED`、`REVIEW_REQUIRED`。
题型预留 `SINGLE_CHOICE`、`MULTIPLE_CHOICE`、`TRUE_FALSE`、`OCR_SHORT_ANSWER`、`OCR_NUMBER`、`OTHER`，当前考试创建完整实现 `SINGLE_CHOICE`，答案值为 `A/B/C/D`。

学生编号由服务端在机构行上执行原子流水号递增，再由数据库唯一约束兜底；客户端不得通过“查询最大值 + 1”生成编号。

## 3. Android Scanner 交接接口

### 获取当前用户与机构

```http
GET /api/v1/me
GET /api/v1/organizations
```

登录使用 `organization_name + teacher_login_name + password`。JWT 固定 `organization_id` 与 `teacher_id`，Android 和 Web 使用同一个 `OrganizationMember`；客户端不能通过请求头切换机构。`/me` 返回当前用户、机构、教师成员和角色。

### 获取班级与 Web 创建的测试

```http
GET /api/v1/classes
GET /api/v1/classes/{class_id}/sessions?status=ACTIVE
```

两个接口都按当前签名机构和教师可见班级过滤。第二个接口只返回 Web 已创建且当前为 `ACTIVE` 的 `AssessmentSession`：

```json
{
  "id": "session-uuid",
  "organization_id": "org-uuid",
  "class_id": "class-uuid",
  "class_name": "初一 A 班",
  "name": "进门测",
  "status": "ACTIVE",
  "question_count": 20,
  "submitted_count": 18,
  "participant_count": 25
}
```

Android 不创建或替换班级、测试、学生和成绩数据。

### 创建或获取扫描会话

```http
POST /api/v1/sessions/{session_id}/scan-session
GET /api/v1/sessions/{session_id}/scan-session
```

POST 按 `(organization_id, assessment_session_id, opened_by_member_id)` 幂等创建/恢复一个 `ScannerSession`。测试必须是 `ACTIVE`，且当前教师必须有该班级权限。GET 只读取当前教师自己的扫描会话。

```json
{
  "id": "scanner-session-uuid",
  "organization_id": "org-uuid",
  "assessment_session_id": "session-uuid",
  "opened_by": "王老师",
  "opened_by_member_id": "membership-uuid",
  "status": "OPEN"
}
```

### 上传扫描图片

```http
POST /api/v1/scans
Content-Type: multipart/form-data
Authorization: Bearer <access_token>
Idempotency-Key: <client_capture_id>
X-Request-ID: <optional-request-id>
```

必需 multipart 字段：`session_id`、`scan_session_id`、`page_token`、`client_capture_id`（UUID）和 `image`（JPEG）。`page_token` 只作为不透明页面 token；服务端只保存哈希，并在同一机构/测试名单范围内尝试关联学生。Android 不把二维码当作最终身份事实。

服务端以 `(organization_id, client_capture_id)` 去重；重试必须继续使用同一个 UUID 和 `Idempotency-Key`，不会创建第二条扫描回执。初始响应：

```json
{
  "server_scan_id": "scan-uuid",
  "session_id": "session-uuid",
  "scan_session_id": "scanner-session-uuid",
  "class_id": "class-uuid",
  "client_capture_id": "capture-uuid",
  "status": "PROCESSING",
  "request_id": "request-uuid",
  "student_name": null,
  "student_code": null,
  "page_type": "ANSWER_SHEET",
  "created_at": "2026-09-15T00:00:00Z",
  "processed_at": null
}
```

### 查询扫描状态

```http
GET /api/v1/scans/{server_scan_id}
```

返回状态 `PROCESSING`、`SUCCESS`、`REVIEW_REQUIRED` 或 `FAILED`。Recognition Service 通过 Backend 的标准识别结果接口使用 `scan_id` 回写状态；Android 只显示状态和队列，不引入 OMR/OCR SDK。

## 4. Recognition Service 交接接口

Recognition Service 只返回标准化识别结果，不把引擎细节传给 Web。

```http
POST /api/v1/sessions/{session_id}/recognition-results
```

请求：

```json
{
  "student_code": "YZ0001",
  "student_qr_token": "<one-time-issued-token>",
  "page_type": "ANSWER_SHEET",
  "answers": [
    {"question_no": 1, "value": "B", "confidence": 0.96},
    {"question_no": 2, "value": "C", "confidence": 0.58}
  ],
  "confidence": 0.77,
  "review_required": false,
  "idempotency_key": "recognition-job-id"
}
```

可使用 `student_id` 或不暴露数据库信息的 `student_qr_token` 替代 `student_code`。服务端会把 `source` 固定为 `recognition`，保存 `page_type` 与整体 `confidence`；整体 confidence 小于 `0.8` 时自动设置 `REVIEW_REQUIRED`。该接口仍遵守同一份 Submission 唯一约束。

## 5. 查询考试与实时结果

```http
GET /api/v1/sessions/{session_id}/results
GET /api/v1/sessions/{session_id}/submissions
```

`results` 返回：

- `participant_count`、`submitted_count`、`pending_count`、`review_required_count`；
- 每题 `correct_answer`、`answered_count`、`counts.A/B/C/D`、`correct_count`、`correct_rate`；
- `students_by_option` 仅在用户点击选项展开时由 Web 显示，课堂大屏默认不显示姓名；
- `students` 的个人答案，供结果页/管理端使用。

正确率分母是该题已提交人数，不是全班名单人数。未提交不计为错误。

SSE：

```http
GET /api/v1/sessions/{session_id}/stream?access_token=<jwt>
Accept: text/event-stream
```

事件名为 `session.update`，事件数据示例：

```json
{"kind":"submission.updated","session_id":"...","student_id":"..."}
```

客户端收到事件后重新读取 `GET /results`，不在客户端自行重算数据库状态。事件包括 `session.started`、`submission.updated`、`session.closed`。

## 6. 重复提交与更新规则

数据库约束：`(session_id, student_id)` 唯一。

- 第一次提交：创建一份当前有效 Submission，`is_update=false`；
- 再次扫描/识别：服务端更新同一 Submission 的状态、来源、元数据和逐题答案，`is_update=true`；
- 不静默创建第二份成绩；
- Session 非 `ACTIVE` 时返回 `409`；不属于课堂名单的学生返回 `422`。

## 7. 错误码

| HTTP | 含义 |
| --- | --- |
| 400 | 请求结构无法处理 |
| 401 | 未登录、Token 无效或过期 |
| 403 | 无组织成员权限，或生产环境禁用 mock submission |
| 404 | 组织、班级、学生或 Session 不存在 |
| 409 | 状态冲突、班级重复、重复加入、编号前缀已冻结或考试已结束 |
| 422 | 字段校验失败、学生不是本场参与者、答案题号非法 |
| 500 | 服务端异常；客户端应记录 request id（如网关提供）并重试前退避 |

## 8. OpenAPI

FastAPI 自动提供：

```text
GET /openapi.json
GET /docs
```

本文件补充跨子系统约定；后续 Android 与 Recognition 对话只按本文件和部署后的 OpenAPI 对接，不读取 Web 内部组件实现。
