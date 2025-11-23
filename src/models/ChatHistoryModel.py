from .BaseDataModel import BaseDataModel
from .db_schemes import ChatHistory
from sqlalchemy.future import select
from sqlalchemy import desc, delete
from typing import Optional, List

MAX_CONVERSATION_MESSAGES = 40
RECENT_HISTORY_LIMIT = 5


class ChatHistoryModel(BaseDataModel):

    def __init__(self, db_client: object):
        super().__init__(db_client=db_client)
        self.db_client = db_client

    @classmethod
    async def create_instance(cls, db_client: object):
        instance = cls(db_client)
        return instance

    async def create_history(
        self,
        user_id: int,
        conversation_id: int,
        prompt: str,
        answer: str,
        model_key: Optional[str] = None,
        doc_types: Optional[List[str]] = None,
        response_time_ms: Optional[int] = None,
        rating: Optional[int] = None,
        is_helpful: Optional[bool] = None,
        fallback_used: Optional[bool] = None,
        retrieved_chunks: Optional[int] = None,
        retrieved_doc_types: Optional[List[str]] = None,
        retrieved_asset_ids: Optional[List[int]] = None,
        resources: Optional[list] = None,
    ):
        async with self.db_client() as session:
            async with session.begin():
                record = ChatHistory(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    prompt=prompt,
                    answer=answer,
                    model_key=model_key,
                    doc_types=doc_types,
                    response_time_ms=response_time_ms,
                    rating=rating,
                    is_helpful=is_helpful,
                    fallback_used=fallback_used,
                    retrieved_chunks=retrieved_chunks,
                    retrieved_doc_types=retrieved_doc_types,
                    retrieved_asset_ids=retrieved_asset_ids,
                    resources=resources,
                )
                session.add(record)
            await session.commit()
            await session.refresh(record)
        await self.trim_history_for_conversation(conversation_id)
        return record

    async def get_recent_history_by_conversation(self, conversation_id: int, limit: int = RECENT_HISTORY_LIMIT):
        async with self.db_client() as session:
            result = await session.execute(
                select(ChatHistory)
                .where(ChatHistory.conversation_id == conversation_id)
                .order_by(desc(ChatHistory.timestamp))
                .limit(limit)
            )
            records = result.scalars().all()
        return list(reversed(records))

    async def get_full_history_by_conversation(self, conversation_id: int):
        async with self.db_client() as session:
            result = await session.execute(
                select(ChatHistory)
                .where(ChatHistory.conversation_id == conversation_id)
                .order_by(ChatHistory.timestamp)
            )
            return result.scalars().all()

    async def trim_history_for_conversation(self, conversation_id: int):
        async with self.db_client() as session:
            result = await session.execute(
                select(ChatHistory.id)
                .where(ChatHistory.conversation_id == conversation_id)
                .order_by(desc(ChatHistory.timestamp))
            )
            ids = [row[0] for row in result.all()]

            if len(ids) <= MAX_CONVERSATION_MESSAGES:
                return

            ids_to_keep = set(ids[:MAX_CONVERSATION_MESSAGES])
            ids_to_delete = [chat_id for chat_id in ids if chat_id not in ids_to_keep]

            if ids_to_delete:
                async with session.begin():
                    await session.execute(
                        delete(ChatHistory).where(ChatHistory.id.in_(ids_to_delete))
                    )
                await session.commit()
