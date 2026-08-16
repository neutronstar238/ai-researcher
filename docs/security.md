# 安全设计（已实现 vs 遗留）

> 依据 spec §19。本文件如实记录当前安全措施与遗留项。

## 已实现

| 域 | 措施 |
|---|---|
| 认证 | Argon2id 密码哈希；JWT access（15min）+ 旋转 refresh（7天）；refresh family 重放撤销；只存 refresh token hash |
| 授权 | §1.2 权限矩阵（owner/researcher/reviewer/guest）服务端逐请求校验；`require_project_role(capability)` 失败关闭；未知角色/能力拒绝 |
| 租户隔离 | 项目查询限定 project_id；证据边跨项目 403；Milvus 检索按 project_id 过滤后回主库鉴权（§19.2） |
| 注入防护 | SQLAlchemy 参数化查询（无字符串拼接 SQL）；Cypher 参数化（neo4j driver 参数）；HTML 转义（前端 escapeHtml + React 默认转义） |
| 文件安全 | 对象 key 服务端生成（扁平 UUID）；上传 SHA-256 服务端重算（§7.8）；下载短期签名 URL（5min）；object_key 前缀校验归属项目 |
| Web 安全 | X-Content-Type-Options/X-Frame-Options/Referrer-Policy 恒加；生产 HSTS + CSP |
| 限流 | 登录 Redis 固定窗口（20/分钟/IP，超限 429） |
| 日志脱敏 | SanitizingFilter 过滤 authorization/token/password/secret/presigned_url/prompt/full_text |
| 密钥 | 只存引用/环境变量；`.env` gitignored；`.env.example` 无真实值；Agent 工具调用不存密钥（arguments_redacted） |

## 遗留（Phase 7 待办）

- ✅ refresh token 已 HttpOnly Cookie 化 + CSRF（§18.3/§19.3）：`ar_refresh` HttpOnly/SameSite=Lax/生产 Secure，前端不入 localStorage，refresh/logout 读 Cookie，Origin 白名单校验。
- ✅ 恶意扫描 quarantine（§19.4）：`core/malware.py` ClamAV `clamscan` 扫描（上传后下载临时文件扫描 → clean/infected/not_scanned）；Asset `status`=ready/quarantined + `scan_status`；Magic Bytes 校验 + 大小上限已实现。Zip Slip 防护（解压隔离）未实现。
- CORS 生产白名单严格化（当前 allow_origins 来自 env，默认 localhost）。
- 密码重置/搜索 Provider/Agent 启动/签名 URL 端点分别限流（当前仅登录）。
- Secret 扫描进 CI、审计日志删除接口未提供（audit_logs 表已建，仅追加 + 查询，普通用户无删除端点）。
- Agent 实验沙箱隔离（§19.5：SSRF 防护、Prompt Injection 隔离；无特权容器已由容器 Runner 提供）。
