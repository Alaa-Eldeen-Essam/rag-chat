from .BaseDataModel import BaseDataModel
from .db_schemes import User
from sqlalchemy.future import select
from sqlalchemy import func, update

class UserModel(BaseDataModel):

    def __init__(self, db_client: object):
        super().__init__(db_client=db_client)
        self.db_client = db_client

    @classmethod
    async def create_instance(cls, db_client: object):
        instance = cls(db_client)
        return instance

    async def create_user(self, username: str, password_hash: str, is_admin: bool = False,
                          department: str = "Global"):
        async with self.db_client() as session:
            async with session.begin():
                user = User(
                    username=username,
                    password_hash=password_hash,
                    is_admin=is_admin,
                    department=department or "Global",
                )
                session.add(user)
            await session.commit()
            await session.refresh(user)
        return user

    async def get_user_by_username(self, username: str):
        async with self.db_client() as session:
            result = await session.execute(
                select(User).where(User.username == username)
            )
            return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: int):
        async with self.db_client() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            return result.scalar_one_or_none()

    async def count_users(self) -> int:
        async with self.db_client() as session:
            result = await session.execute(select(func.count(User.id)))
            return result.scalar_one()

    async def update_last_login(self, user_id: int):
        async with self.db_client() as session:
            async with session.begin():
                await session.execute(
                    update(User)
                    .where(User.id == user_id)
                    .values(last_login=func.now())
                )
            await session.commit()

    async def ensure_initial_admin(self, username: str, password_hash: str):
        user_count = await self.count_users()
        if user_count and user_count > 0:
            return
        await self.create_user(username=username, password_hash=password_hash, is_admin=True)

    async def update_department(self, user_id: int, department: str):
        async with self.db_client() as session:
            async with session.begin():
                await session.execute(
                    update(User)
                    .where(User.id == user_id)
                    .values(department=department)
                )
            await session.commit()

    async def update_username(self, user_id: int, username: str):
        async with self.db_client() as session:
            async with session.begin():
                await session.execute(
                    update(User)
                    .where(User.id == user_id)
                    .values(username=username)
                )
            await session.commit()

    async def reset_password(self, user_id: int, password_hash: str):
        async with self.db_client() as session:
            async with session.begin():
                await session.execute(
                    update(User)
                    .where(User.id == user_id)
                    .values(password_hash=password_hash)
                )
            await session.commit()
