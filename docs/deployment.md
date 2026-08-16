# Docker 一键部署（spec §20）

> 一条命令起完整平台（PostgreSQL/Redis/MinIO/Neo4j/etcd/Milvus + API + 前端）。
> 登录：`owner@airesearcher.local / demo-password`（`SEED_DEMO=1` 时自动播种）。

## 快速开始

```bash
cp .env.example .env            # 改生产密钥（JWT_SIGNING_KEY 等）
docker compose up -d --build    # 构建并后台启动全部服务
docker compose logs -f api      # 看 API 日志（含迁移/播种）
```

- 前端：<http://localhost:8080>
- API 文档：<http://localhost:8000/api/docs>
- 健康检查：<http://localhost:8000/health/ready>

## 服务清单

| 服务 | 端口（仅本机） | 说明 |
|---|---|---|
| postgres | 5432 | 权威事实源 |
| redis | 6379 | 缓存/限流/Celery broker |
| minio | 9000 / 9001 | 对象存储 |
| neo4j | 7474 / 7687 | 图投影 |
| etcd | — | Milvus 元数据 |
| milvus | 19530 / 9091 | 向量索引 |
| api | 8000 | FastAPI（启动时自动 `alembic upgrade head` + 可选 seed） |
| frontend | 8080 | React 静态（nginx） |

## 生产注意事项

- 改 `JWT_SIGNING_KEY`；生产 `APP_ENV=production` 会启用 HSTS/CSP + 校验密钥。
- 生产把各服务端口绑定到内网/去掉 `127.0.0.1` 暴露（compose 默认仅本机）。
- 外部 Provider（LLM/Embedding/OCR）经 `.env` 注入（`LLM_PROVIDER/API_KEY/BASE_URL/MODEL`、`EMBEDDING_PROVIDER/MODEL`）。
- 备份/恢复见 `docs/runbook-backup-restore.md`。

## 停止 / 清理

```bash
docker compose down            # 停止（保留数据卷）
docker compose down -v         # 停止并删除数据卷（危险）
```
