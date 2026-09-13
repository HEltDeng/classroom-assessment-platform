# 独立测试环境部署

本项目与既有业务使用独立目录、独立 systemd unit、独立端口、独立 EnvironmentFile、独立 PostgreSQL database/role 和独立 Nginx server block。

## 目标隔离

```text
应用根目录：/opt/classroom-assessment-platform
当前版本：/opt/classroom-assessment-platform/current
服务：classroom-assessment-api.service
本地 API：127.0.0.1:8101
EnvironmentFile：/etc/classroom-assessment-platform/backend.env
PostgreSQL database：classroom_assessment
PostgreSQL role：classroom_assessment
Nginx 配置：classroom-assessment
```

既有站点和 API 的服务、目录、数据库、证书与 Nginx server block 不作为替换目标。

## 部署入口

Windows 上使用：

```powershell
.\scripts\Invoke-ClassroomAssessmentDeploy.ps1 -Action Inspect
.\scripts\Invoke-ClassroomAssessmentDeploy.ps1 -Action Deploy -WebHost assessment.mychangliapp.cn
```

入口从本机既有 DPAPI 安全记录读取 SSH key/sudo 凭据。凭据不作为参数、不写入仓库、不输出到日志。部署包只从 clean Git commit 与本地 `web/dist` 产生，不包含数据库、`.env`、虚拟环境或密钥。

## 部署流程

1. 本地完成 backend tests、Alembic check 和 web production build；
2. 只读检查既有服务、Nginx、磁盘和目标端口；
3. 安装/确认 PostgreSQL 与 Python runtime；
4. 在独立数据库中执行 Alembic migration；
5. 创建独立 systemd unit，绑定 loopback 8101；
6. 上传并切换 `/opt/classroom-assessment-platform/current`；失败时保留旧版本目录，不删除用户数据；
7. 安装 HTTP Nginx server block；如 ACME 验证成功，再安装 HTTPS server block 并 reload；
8. 验证服务 active、端口、health、readiness、OpenAPI、Web 首页、SSE、原有官网/API 与新错误日志。

可信 HTTPS 证书必须由该域名的可信 CA 签发并经过客户端握手验证；如果 DNS/ACME 条件不满足，部署报告必须标记 `PENDING_CERTIFICATE`，不能把 HTTP 或自签名证书写成 HTTPS PASS。
