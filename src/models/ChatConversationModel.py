from .BaseDataModel import BaseDataModel
from .db_schemes import ChatConversation
from sqlalchemy.future import select
from sqlalchemy import func, update
import re


class ChatConversationModel(BaseDataModel):

    def __init__(self, db_client: object):
        super().__init__(db_client=db_client)
        self.db_client = db_client

    @classmethod
    async def create_instance(cls, db_client: object):
        instance = cls(db_client)
        return instance

    async def create_conversation(self, user_id: int, initial_prompt: str):
        title = self._generate_conversation_title(initial_prompt)

        async with self.db_client() as session:
            async with session.begin():
                conversation = ChatConversation(
                    conversation_user_id=user_id,
                    conversation_title=title,
                )
                session.add(conversation)
            await session.commit()
            await session.refresh(conversation)
        return conversation

    async def get_conversation(self, conversation_id: int, user_id: int):
        async with self.db_client() as session:
            result = await session.execute(
                select(ChatConversation).where(
                    ChatConversation.conversation_id == conversation_id,
                    ChatConversation.conversation_user_id == user_id,
                )
            )
            return result.scalar_one_or_none()

    async def list_conversations(self, user_id: int):
        async with self.db_client() as session:
            result = await session.execute(
                select(ChatConversation)
                .where(ChatConversation.conversation_user_id == user_id)
                .order_by(
                    ChatConversation.updated_at.desc(),
                    ChatConversation.created_at.desc()
                )
            )
            return result.scalars().all()

    async def update_conversation_title(self, conversation_id: int, user_id: int, title: str):
        async with self.db_client() as session:
            async with session.begin():
                await session.execute(
                    update(ChatConversation)
                    .where(
                        ChatConversation.conversation_id == conversation_id,
                        ChatConversation.conversation_user_id == user_id,
                    )
                    .values(conversation_title=title)
                )
            await session.commit()

    async def touch_conversation(self, conversation_id: int):
        async with self.db_client() as session:
            async with session.begin():
                await session.execute(
                    update(ChatConversation)
                    .where(ChatConversation.conversation_id == conversation_id)
                    .values(updated_at=func.now())
                )
            await session.commit()

    def _generate_conversation_title(self, initial_prompt: str) -> str:
        if not initial_prompt:
            return "New Conversation"

        prompt = initial_prompt.strip()
        prompt = re.sub(r'\s+', ' ', prompt)

        if len(prompt) <= 60:
            return prompt.capitalize()

        truncated = prompt[:57].rsplit(' ', 1)[0]
        return f"{truncated.capitalize()}..."
