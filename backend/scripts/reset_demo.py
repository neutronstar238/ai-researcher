"""重置 demo 数据库：DROP public schema + 重建（用于干净状态回归测试）。

用法：cd backend && .\.venv\Scripts\python.exe scripts/reset_demo.py
之后手动跑 `alembic upgrade head` + `python -m app.seed --profile demo`。
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.db.session import dispose_engine, get_engine


async def drop_schema() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await dispose_engine()


def main() -> int:
    asyncio.run(drop_schema())
    print("public schema dropped + recreated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
