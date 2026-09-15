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

`/me` 返回当前固定机构、教师成员和角色；`/organizations` 为兼容旧客户端仅返回当前机构。数据库字段始终使用 `student_code`。

### 获取班级与学生

```http
GET /api/v1/classes
GET /api/v1/classes/{class_id}
GET /api/v1/classes/{class_id}/students
GET /api/v1/students?search=<name-or-code>
```

`GET /classes/{class_id}/students` 只返回当前有效加入该班级的学生。历史移出记录不影响学生和历史课堂。

学生主库与班级关系管理：

```http
POST /api/v1/organizations
GET /api/v1/teachers
POST /api/v1/teachers
GET /api/v1/subjects
POST /api/v1/subjects
GET /api/v1/time-slots
POST /api/v1/time-slots
GET /api/v1/course-days
POST /api/v1/course-days
PATCH /api/v1/course-days/{weekday}
GET /api/v1/students/import/template.xlsx
POST /api/v1/students/import/preview
POST /api/v1/students/import/confirm
PATCH /api/v1/students/{student_id}
POST /api/v1/classes/{class_id}/student-memberships
POST /api/v1/students/{student_id}/transfer
POST /api/v1/students/{student_id}/qr-token
```

`POST /students/import/preview` 只读取文件并返回 `PREPARE_CREATE`、`EXISTING_SUSPECT`、`DUPLICATE_IN_ORG`、`DUPLICATE_INPUT`、`EMPTY_NAME`、`INVALID_STAGE` 等状态；只有 `POST /students/import/confirm` 才写入 Student 或 ClassEnrollment。一个同名学生可默认建议复用，多个同名学生必须选择具体 `student_id`、新建或跳过，姓名不是主键。

`POST /students/{student_id}/transfer` 关闭原班级的 active enrollment 并建立目标班级关系，学生 UUID、机构编号、考试和历史成绩保持不变。移出班级只关闭 enrollment，机构学生主库记录仍保留。

### 获取 Active Exam

```http
GET /api/v1/sessions?status=ACTIVE
GET /api/v1/sessions/{session_id}
```

返回包含 `class_id`、`class_name`、`subject_name`、`exam_type`、`question_count`、`total_score`、状态和题目标准答案/分值。Scanner 通常只需要选择当前班级的 Active Exam。

考试创建：

```http
POST /api/v1/sessions
```

请求至少包含 `class_id`、`question_count`、逐题 `answer_keys`；可选 `subject_id`、`exam_type` 和逐题 `points`。Session 兼容旧接口名称，但 Web 页面统一使用“新建考试/发布考试”，不使用“布置作业”。

### 提交标准化答题结果

```http
POST /api/v1/sessions/{session_id}/submissions
```

请求：

```json
{
  "student_id": "student-uuid",
  "answers": [
    {"question_no": 1, "value": "B", "confidence": 0.99},
    {"question_no": 2, "value": "C", "confidence": 0.91}
  ],
  "source": "android",
  "review_required": false,
  "idempotency_key": "scanner-device-job-id"
}
```

`source`：`android`、`mock`、`recognition`。Android 正式调用使用 `android`。答案题号必须唯一且属于本场题目；v1 的 `value` 只能是 `A/B/C/D`。

响应：

```json
{
  "id": "submission-uuid",
  "session_id": "session-uuid",
  "student_id": "student-uuid",
  "status": "SUBMITTED",
  "source": "android",
  "page_type": null,
  "confidence": null,
  "is_update": false,
  "correct_count": 4,
  "question_count": 4,
  "submitted_at": "2026-09-13T00:00:00Z",
  "updated_at": "2026-09-13T00:00:00Z"
}
```

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
