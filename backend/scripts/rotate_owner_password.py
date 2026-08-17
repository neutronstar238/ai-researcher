"""把 owner 演示账号密码换成随机强值（公网暴露前加固）。"""

from __future__ import annotations

import asyncio
import secrets

from sqlalchemy import update

from app.core.security import hash_password
from app.db.models import User
from app.db.session import get_session_factory


async def main() -> None:
    new_password = "Ar!" + secrets.token_urlsafe(14)
    hashed = hash_password(new_password)
    async with get_session_factory()() as session:
        result = await session.execute(
            update(User)
            .where(User.email == "owner@airesearcher.local")
            .values(password_hash=hashed)
        )
        await session.commit()
        print("ROWS_UPDATED=", result.rowcount)
    print("NEW_PASSWORD=", new_password)


if __name__ == "__main__":
    asyncio.run(main())
