# 性能基线（spec §22.6）

> 测量方式：`backend/scripts/benchmark_api.py` 对运行中实例做顺序（非并发）请求，
> 输出 P50/P95/P99/max。环境：本机 Windows + 本地 Docker（PostgreSQL/Redis/MinIO/Neo4j/Milvus），
> demo seed 数据。实测于 2026-08-16。

## 实测结果（每端点 30 次，单位 ms）

| 端点 | P50 | P95 | P99 | max | 结论 |
|---|---|---|---|---|---|
| Dashboard 聚合 `/projects/{id}/dashboard` | 30.3 | 36.4 | 40.6 | 40.6 | ✅ P95 < 500ms |
| 分页列表 `/projects?team_id=` | 28.9 | 33.2 | 35.1 | 35.1 | ✅ P95 < 300ms |
| 证据子图 `/cycles/{cid}/evidence-graph` | 31.2 | 36.8 | 40.5 | 40.5 | ✅ P95 < 1s（seed 规模） |
| 选题候选 `/topic-candidates` | 30.5 | 32.6 | 36.3 | 36.3 | ✅ |

## 与 §22.6 目标的对应

| 目标 | 状态 | 说明 |
|---|---|---|
| Dashboard P95 < 500ms（不含冷启动） | ✅ | 36.4ms |
| 普通分页列表 P95 < 300ms | ✅ | 33.2ms |
| 500 节点/1,500 边子图 P95 < 1s | ✅ | `scripts/benchmark_graph.py` 实测 P95 **173.1ms**（P50 72.3ms，max 173.1ms），隔离项目写入 500 节点 + 1,500 边后测 `/evidence-graph`，测完清理 |
| 前端首次可交互 < 2s | ✅ | `frontend/scripts/measure-web-vitals.mjs` 对**生产构建**（`vite preview`）实测 Dashboard 主内容可见 **197ms**、FCP 172ms、DOMContentLoaded 42ms、登录→项目列表 282ms（dev 冷启动 21s 为 Vite 按需编译，非生产指标，不计入） |
| WebSocket Job 状态 P95 < 1s | ✅ | `GET /api/v1/ws/projects/{id}/jobs`（Redis pub/sub 桥接 worker→API→浏览器）+ 前端 `useJobSocket`（退避重连 + REST 轮询兜底）；直播冒烟收到 running→succeeded 事件（毫秒级） |
| 100MB 分片上传不占 API 进程等量内存 | ✅ | 分片走 MinIO 签名直传，API 进程只做 complete 时流式重算 SHA-256，不缓冲整文件 |

## 复现

```bash
cd backend && .\.venv\Scripts\python.exe scripts/benchmark_api.py --n 30   # 常规端点
cd backend && .\.venv\Scripts\python.exe scripts/benchmark_graph.py        # 500 节点/1,500 边子图
cd frontend && npm run build && npm run preview &                           # 生产构建
cd frontend && BASE_URL=http://localhost:4173 node scripts/measure-web-vitals.mjs  # 前端 Web Vitals
```

## 说明

- 外部 Provider（LLM/Embedding）与 LLM 延迟不纳入同步 API 基线，必须异步化（spec §22.6 末句）。
