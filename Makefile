# AI-Researcher 跨平台任务入口（spec §26.4）
SHELL := /bin/sh

.PHONY: help up down logs migrate seed test lint build

help:
	@echo "AI-Researcher 常用命令："
	@echo "  make up         启动核心依赖 (postgres/redis/minio/neo4j/milvus)"
	@echo "  make down       停止并移除容器"
	@echo "  make migrate    执行 Alembic 迁移 (upgrade head)"
	@echo "  make seed       写入确定性 Demo Seed"
	@echo "  make test       后端单元测试"
	@echo "  make lint       后端 lint/typecheck"
	@echo "  make build      前端生产构建"
	@echo "  make dev-api    本地启动 API (uvicorn --reload)"
	@echo "  make dev-web    本地启动前端 (vite dev)"

up:
	docker compose up -d postgres redis minio neo4j etcd milvus

down:
	docker compose down

logs:
	docker compose logs -f

migrate:
	cd backend && alembic upgrade head

seed:
	cd backend && python -m app.seed --profile demo

test:
	cd backend && pytest -q

lint:
	cd backend && ruff check app && mypy app

build:
	cd frontend && npm run build

dev-api:
	cd backend && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

dev-web:
	cd frontend && npm run dev
