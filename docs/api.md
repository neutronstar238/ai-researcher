# API 概览（已实现）

> Base URL `/api/v1`；错误信封 `{error:{code,message,field_errors,details,trace_id}}`（spec §18.1）。
> OpenAPI 文档：运行后端后访问 `/api/docs`。

## 认证 / 团队（§18.3/§18.4）
- `POST /auth/login`（限流）、`POST /auth/refresh`、`POST /auth/logout`、`GET /auth/me`
- `GET/POST /teams`、`GET/POST/PATCH/DELETE /teams/{id}/members`

## 项目 / 周期（§18.4）
- `GET/POST /projects`、`GET/PATCH /projects/{id}`、`POST /projects/{id}:archive|restore`
- `GET/POST/PATCH/DELETE /projects/{id}/members`
- `GET/POST /projects/{id}/cycles`、`POST /cycles/{id}:activate|complete`
- `GET /projects/{id}/dashboard`、`GET /projects/{id}/evidence-coverage?cycles=6`

## 生命周期（§12.5）
- `GET /projects/{id}/cycles/{cid}/lifecycle`
- `POST /projects/{id}/cycles/{cid}/stages/{key}:start|complete|block|resume|reopen`
- `GET /projects/{id}/cycles/{cid}/stages/{key}/gate`

## 证据图（§7.9/§14）
- `GET /projects/{id}/cycles/{cid}/evidence-graph`
- `POST/GET/PATCH/DELETE /projects/{id}/evidence/nodes[/{node_id}]`
- `POST/PATCH/DELETE /projects/{id}/evidence/edges[/{edge_id}]`

## 文献（§13.6）
- `POST /projects/{id}/literature-search-runs`（202+run_id，异步 arXiv 检索）、`GET /projects/{id}/literature-search-runs`、`GET .../{run_id}`（轮询 Job 状态/结果）
- `GET/POST /projects/{id}/papers`
- `GET/POST /projects/{id}/topic-candidates`、`POST /topic-candidates/{id}:accept|reject`

## 审批（§18.6）
- `GET /projects/{id}/approvals?status=`、`GET /approvals/{id}`、`POST /approvals/{id}:approve|reject`

## 审计（§19.6）
- `GET /projects/{id}/audit-logs?limit=`（需 `manage_members`；审批决定与阶段完成自动落审计）

## 资产 / 向量（§18.5/§13.4）
- `POST /projects/{id}/assets/uploads:initiate`（`part_count`=1 单分片 / >1 返回每片签名 URL）、`POST /assets/uploads/{uid}:complete`（分片模式传 `object_key`+`parts[{part_number,etag}]`）
- `GET /projects/{id}/assets`、`GET /assets/{id}/download-url`
- `POST /projects/{id}/vector/store`、`POST /projects/{id}/vector/search`

## 实验（§15.6）
- `GET/POST /projects/{id}/experiments`、`GET /experiments/{id}`
- `POST /experiments/{id}/runs`、`GET/POST /experiment-runs/{id}:cancel`、`GET /experiment-runs/{id}/reproducibility`
- `POST/GET /experiment-runs/{id}/metrics`、`POST /experiment-runs/{id}/datasets|artifacts`

## 数据集（§18.5）
- `GET/POST /projects/{id}/datasets`、`GET /datasets/{id}`、`POST /datasets/{id}/versions`

## Agent（§16.9）
- `GET /projects/{id}/agents`、`POST/GET /projects/{id}/agent-tasks`、`POST /agent-tasks/{id}:cancel|retry|run`（`:run` 真实调用已配置的 LLM）
- `POST/GET /agent-tasks/{id}/tool-calls`、`POST/GET /agent-memories`、`GET /agent-memories/search`

## 写作 / 复盘（§17.4/§17.5）
- `GET/POST /projects/{id}/documents`、`GET /documents/{id}`
- `POST/GET /documents/{id}/versions`、`POST /documents/{id}/claims|citations`
- `POST /documents/{id}:integrity-check|:export`
- `POST /documents/{id}:suggestions`、`GET /documents/{id}/suggestions`、`POST .../suggestions/{sid}:accept|reject`（Agent Diff）
- `POST /projects/{id}/cycles/{cid}/reflection-runs`、`GET /cycles/{cid}/reflection`、`POST .../recommendations/{rid}:accept`

## 系统 / 健康
- `GET /health/live`、`GET /health/ready`、`GET /api/v1/system/health/summary`
- `GET /metrics`（Prometheus：HTTP 计数/延迟直方图 + `ar_audit_events_total`/`ar_experiment_runs_total` 业务计数器）

完整接口契约以运行中实例的 OpenAPI（`/api/docs`）为准。
