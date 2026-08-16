# 备份与恢复 Runbook（spec §22.5）

> 权威事实源只有 **PostgreSQL**；MinIO 存原始二进制资产；Neo4j/Milvus 是
> PostgreSQL 的**派生投影**，可从主库重建（spec §3.4）。Redis 为限流/缓存/Celery
> broker，属可丢弃状态。备份/恢复围绕「主库 + 对象存储」两个持久化源展开。

## 1. 需要备份的内容

| 组件 | 数据 | 是否必需备份 | 说明 |
|---|---|---|---|
| PostgreSQL | 全部业务事实（身份/项目/生命周期/证据/实验/写作/审计） | ✅ 必需 | 权威源，`pg_dump` |
| MinIO | 资产、导出物、PDF 等原始二进制 | ✅ 必需 | `mc mirror` 或 bucket 导出 |
| Neo4j | 证据图投影 | ❌ 可重建 | `dispatcher --rebuild <project>` |
| Milvus | 向量索引（paper_chunks / agent_memories） | ❌ 可重建 | 从 PG 重新 embedding 入库 |
| Redis | 限流窗口 / 会话缓存 / Celery broker | ❌ 可丢弃 | 丢失仅影响速率窗口与未消费队列 |

## 2. 备份（Backup）

### 2.1 PostgreSQL（权威源）

```bash
# 单库逻辑备份（幂等、可移植）
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-airesearcher}" \
  -d "${POSTGRES_DB:-airesearcher}" --clean --if-exists > backup/airesearcher-$(date +%F).sql

# 或本机 pg_dump（端口按 .env，默认 5432）
pg_dump "postgresql://airesearcher:airesearcher@localhost:5432/airesearcher" \
  --clean --if-exists > backup/airesearcher.sql
```

> 生产建议叠加 `pg_dump -Fc`（自定义格式，支持并行恢复）与 WAL 归档（PITR），
> 按 RPO 需求选择；本 runbook 提供最小可恢复路径。

### 2.2 MinIO（对象存储）

```bash
# 用 mc 客户端镜像整个 bucket
mc alias set local http://localhost:9000 "${MINIO_ACCESS_KEY:-minioadmin}" "${MINIO_SECRET_KEY:-minioadmin}"
mc mirror --overwrite local/assets backup/minio-assets/
```

## 3. 恢复（Restore）

恢复顺序：**先 PostgreSQL → 再 MinIO → 最后重建派生投影 → 重启应用**。

```bash
# 1) 恢复主库（空库上执行）
docker compose exec -T postgres psql -U "${POSTGRES_USER:-airesearcher}" \
  -d "${POSTGRES_DB:-airesearcher}" < backup/airesearcher.sql

# 2) 恢复 MinIO 资产
mc mirror --overwrite backup/minio-assets/ local/assets

# 3) 重建 Neo4j 投影（对每个项目；或由 Celery beat 定时 outbox 自动补齐）
cd backend && .\.venv\Scripts\python.exe -m app.workers.dispatcher --rebuild <project_id>

# 4) 重建 Milvus 向量索引（从 PG 论文/Agent memory 重新 embedding）
#    （脚本见 docs/status.md 遗留项；未实现前需手动重跑入库流程）

# 5) 重启后端/前端，健康检查
docker compose restart api frontend
curl http://localhost:8000/health/ready
```

## 4. 验证恢复完整性

```bash
# 主库行数与备份一致
docker compose exec postgres psql -U airesearcher -d airesearcher \
  -c "SELECT count(*) FROM projects;"

# 投影重建结果
cd backend && .\.venv\Scripts\python.exe -m app.workers.dispatcher --rebuild <project_id>
# 输出 neo4j_nodes / neo4j_edges 计数，与 PG evidence_nodes/evidence_edges 对齐

# 资产可下载（签名 URL 仍有效）
curl -X GET "http://localhost:8000/api/v1/projects/<project_id>/assets/<asset_id>/download-url"
```

## 5. 演练与自动化

- 至少每季度做一次**恢复演练**（backup → 空环境 restore → 完整性校验）。
- CI 可加 `pg_dump` 冒烟：dump 成功且 `restore --list` 含全部表。
- 备份文件不得提交到仓库（`backup/` 加入 `.gitignore`）；生产加密存储（如 S3/KMS）。
