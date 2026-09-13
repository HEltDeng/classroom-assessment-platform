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
X-Organization-Id: <organization_id>
Content-Type: application/json
```

`X-Organization-Id` 用于组织级接口；服务端会再次校验当前用户的组织成员关系。

登录：

```http
POST /api/v1/auth/login
```

```json
{
  "email": "teacher@example.com",
  "password": "<password>"
}
```

成功响应：

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "user": {"id": "...", "email": "...", "display_name": "..."}
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
| Organization / OrganizationSettings | 多机构隔离及机构展示配置 |
| User / OrganizationMember | 登录用户与组织角色 |
| Class | 组织内班级，可归档 |
| Student | 组织内学生；`organization_id + student_code` 唯一 |
| ClassEnrollment | 学生进出班级的历史关系；移出不删除 Student |
| AssessmentSession | 一次班级课堂答题活动 |
| SessionParticipant | 创建课堂时的班级名单快照 |
| Question / AnswerKey | 本场题目与标准答案 |
| Submission / StudentAnswer | 学生当前有效答题结果与逐题答案 |

课堂状态：`DRAFT`、`ACTIVE`、`CLOSED`、`ARCHIVED`。

学生状态：`PENDING`、`SUBMITTED`、`REVIEW_REQUIRED`。
题型枚举已预留 `MCQ`、`TEXT`；v1 只接受 `A/B/C/D`。

## 3. Android Scanner 交接接口

### 获取当前用户与机构

```http
GET /api/v1/me
GET /api/v1/organizations
```

`/me` 返回 memberships；`/organizations` 返回用户可访问的机构及 `settings.student_code_label`。数据库字段始终使用 `student_code`。

### 获取班级与学生

```http
GET /api/v1/classes
GET /api/v1/classes/{class_id}
GET /api/v1/classes/{class_id}/students
GET /api/v1/students?search=<name-or-code>
```

`GET /classes/{class_id}/students` 只返回当前有效加入该班级的学生。历史移出记录不影响学生和历史课堂。

### 获取 Active Session

```http
GET /api/v1/sessions?status=ACTIVE
GET /api/v1/sessions/{session_id}
```

返回包含 `class_id`、`class_name`、`question_count`、状态和题目标准答案。Scanner 通常只需要选择当前班级的 Active Session。

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
  "student_code": "S001",
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

可使用 `student_id` 替代 `student_code`。服务端会把 `source` 固定为 `recognition`，保存 `page_type` 与整体 `confidence`；整体 confidence 小于 `0.8` 时自动设置 `REVIEW_REQUIRED`。该接口仍遵守同一份 Submission 唯一约束。

## 5. 查询课堂与实时结果

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
| 409 | 状态冲突、班级重复、重复加入或课堂已结束 |
| 422 | 字段校验失败、学生不是本场参与者、答案题号非法 |
| 500 | 服务端异常；客户端应记录 request id（如网关提供）并重试前退避 |

## 8. OpenAPI

FastAPI 自动提供：

```text
GET /openapi.json
GET /docs
```

本文件补充跨子系统约定；后续 Android 与 Recognition 对话只按本文件和部署后的 OpenAPI 对接，不读取 Web 内部组件实现。
