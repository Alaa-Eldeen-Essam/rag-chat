from .BaseDataModel import BaseDataModel
from .db_schemes import SummaryRecord
from sqlalchemy.future import select
from sqlalchemy import delete
from typing import Optional, List


class SummaryModel(BaseDataModel):

    def __init__(self, db_client: object):
        super().__init__(db_client=db_client)
        self.db_client = db_client

    @classmethod
    async def create_instance(cls, db_client: object):
        instance = cls(db_client)
        return instance

    async def create_summary(
        self,
        user_id: int,
        project_id: int,
        summary_text: str,
        request_payload: dict,
        chunk_ids: Optional[List[int]] = None,
        chunk_count: Optional[int] = None,
        asset_id: Optional[int] = None,
        prompt_text: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
    ) -> SummaryRecord:

        async with self.db_client() as session:
            async with session.begin():
                record = SummaryRecord(
                    user_id=user_id,
                    project_id=project_id,
                    asset_id=asset_id,
                    summary_text=summary_text,
                    request_payload=request_payload or {},
                    chunk_ids=chunk_ids or [],
                    chunk_count=chunk_count or (len(chunk_ids) if chunk_ids else 0),
                    prompt_text=prompt_text,
                    max_output_tokens=max_output_tokens,
                )
                session.add(record)
            await session.commit()
            await session.refresh(record)
        return record

    async def list_project_summaries(self, project_id: int, limit: int = 20) -> List[SummaryRecord]:
        async with self.db_client() as session:
            result = await session.execute(
                select(SummaryRecord)
                .where(SummaryRecord.project_id == project_id)
                .order_by(SummaryRecord.created_at.desc())
                .limit(limit)
            )
            return result.scalars().all()

    async def get_summary_by_id(self, summary_id: int) -> Optional[SummaryRecord]:
        async with self.db_client() as session:
            result = await session.execute(
                select(SummaryRecord).where(SummaryRecord.summary_id == summary_id)
            )
            return result.scalar_one_or_none()

    async def delete_summary(self, summary_id: int) -> bool:
        async with self.db_client() as session:
            async with session.begin():
                result = await session.execute(
                    select(SummaryRecord).where(SummaryRecord.summary_id == summary_id)
                )
                record = result.scalar_one_or_none()
                if not record:
                    return False
                await session.delete(record)
            await session.commit()
        return True

    async def delete_summaries_by_asset_id(self, asset_id: int) -> int:
        async with self.db_client() as session:
            async with session.begin():
                result = await session.execute(
                    delete(SummaryRecord).where(SummaryRecord.asset_id == asset_id).returning(SummaryRecord.summary_id)
                )
            await session.commit()
            deleted_rows = result.fetchall() if result else []
        return len(deleted_rows)
