from .BaseDataModel import BaseDataModel
from .db_schemes import Asset
from sqlalchemy.future import select
from sqlalchemy import or_

class AssetModel(BaseDataModel):

    def __init__(self, db_client: object):
        super().__init__(db_client=db_client)
        self.db_client = db_client

    @classmethod
    async def create_instance(cls, db_client: object):
        instance = cls(db_client)
        return instance

    async def create_asset(self, asset: Asset):

        async with self.db_client() as session:
            async with session.begin():
                if not asset.asset_document_type or not asset.asset_document_type.strip():
                    asset.asset_document_type = "general"
                else:
                    asset.asset_document_type = asset.asset_document_type.strip().lower()
                session.add(asset)
            await session.commit()
            await session.refresh(asset)
        return asset

    def _can_user_access(self, asset: Asset, current_user) -> bool:
        if asset.asset_is_private is False:
            return True

        if current_user is None:
            return False

        if getattr(current_user, "is_admin", False):
            return True

        if asset.asset_user_id is None:
            return True

        return asset.asset_user_id == getattr(current_user, "id", None)

    async def get_all_project_assets(self, asset_project_id: int, asset_type: str, current_user):

        async with self.db_client() as session:
            stmt = select(Asset).where(
                Asset.asset_project_id == asset_project_id,
                Asset.asset_type == asset_type
            )

            if current_user and not getattr(current_user, "is_admin", False):
                stmt = stmt.where(
                    or_(
                        Asset.asset_is_private.is_(False),
                        Asset.asset_user_id == getattr(current_user, "id", None)
                    )
                )

            result = await session.execute(stmt)
            records = result.scalars().all()
        return records

    async def get_asset_record(self, asset_project_id: int, asset_name: str, current_user):

        async with self.db_client() as session:
            stmt = select(Asset).where(
                Asset.asset_project_id == asset_project_id,
                Asset.asset_name == asset_name
            )
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()

            if record is None:
                return None, False

            if not self._can_user_access(asset=record, current_user=current_user):
                return None, True
        return record, True
