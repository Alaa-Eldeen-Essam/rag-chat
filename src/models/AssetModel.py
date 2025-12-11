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
                # Normalize visibility
                visibility = (getattr(asset, "asset_visibility", None) or "private").strip().lower()
                if visibility not in ("private", "department", "global"):
                    visibility = "private"
                asset.asset_visibility = visibility
                session.add(asset)
            await session.commit()
            await session.refresh(asset)
        return asset

    def _can_user_access(self, asset: Asset, current_user) -> bool:
        if current_user is None:
            return False

        if getattr(current_user, "is_admin", False):
            return True

        # Owner always has access
        if asset.asset_user_id == getattr(current_user, "id", None):
            return True

        visibility = getattr(asset, "asset_visibility", None) or (
            "private" if getattr(asset, "asset_is_private", True) else "global"
        )
        visibility = visibility.lower()
        asset_dept = getattr(asset, "asset_department", None)
        user_dept = getattr(current_user, "department", None)

        if visibility == "global":
            return True
        if visibility == "department" and asset_dept and user_dept:
            if isinstance(asset_dept, list):
                return user_dept in asset_dept
            elif isinstance(asset_dept, str):
                return user_dept == asset_dept

        # default / private
        return False

    async def get_all_project_assets(self, asset_project_id: int, asset_type: str, current_user):

        async with self.db_client() as session:
            stmt = select(Asset).where(
                Asset.asset_project_id == asset_project_id,
                Asset.asset_type == asset_type
            )

            result = await session.execute(stmt)
            records = result.scalars().all()

        if current_user and not getattr(current_user, "is_admin", False):
            return [a for a in records if self._can_user_access(a, current_user)]
        return records

    async def get_all_accessible_assets(self, asset_type: str, current_user):

        async with self.db_client() as session:
            stmt = select(Asset).where(Asset.asset_type == asset_type)

            result = await session.execute(stmt)
            records = result.scalars().all()

        if current_user and not getattr(current_user, "is_admin", False):
            return [a for a in records if self._can_user_access(a, current_user)]
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

    async def get_asset_by_id(self, asset_id: int, current_user):

        async with self.db_client() as session:
            stmt = select(Asset).where(Asset.asset_id == asset_id)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()

            if record is None:
                return None, False

            if not self._can_user_access(asset=record, current_user=current_user):
                return None, True
        return record, True

    async def delete_asset(self, asset: Asset):
        async with self.db_client() as session:
            async with session.begin():
                await session.delete(asset)
            await session.commit()
