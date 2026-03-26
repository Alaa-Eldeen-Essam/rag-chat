from .BaseDataModel import BaseDataModel
from .db_schemes import Project
from sqlalchemy.future import select
from sqlalchemy import func, or_

class ProjectModel(BaseDataModel):

    def __init__(self, db_client: object):
        super().__init__(db_client=db_client)
        self.db_client = db_client

    @classmethod
    async def create_instance(cls, db_client: object):
        instance = cls(db_client)
        return instance

    async def create_project(self, project: Project):
        async with self.db_client() as session:
            async with session.begin():
                session.add(project)
            await session.commit()
            await session.refresh(project)
        
        return project

    def _can_user_access(self, project: Project, current_user) -> bool:
        if project.project_is_private is False:
            return True

        if current_user is None:
            return False

        if getattr(current_user, "is_admin", False):
            return True

        if project.project_user_id is None:
            return True

        return project.project_user_id == getattr(current_user, "id", None)

    async def get_project_or_create_one(
        self,
        project_id: int,
        current_user,
        create_if_missing: bool = True,
        is_private: bool = True,
        require_owner: bool = False,
    ):
        async with self.db_client() as session:
            result = await session.execute(
                select(Project).where(Project.project_id == project_id)
            )
            project = result.scalar_one_or_none()

            if project:
                if not self._can_user_access(project=project, current_user=current_user):
                    return None, "forbidden"

                if require_owner and not getattr(current_user, "is_admin", False):
                    if project.project_user_id not in (None, getattr(current_user, "id", None)):
                        return None, "forbidden"

                updated = False
                if project.project_user_id is None and getattr(current_user, "id", None) is not None:
                    if require_owner or getattr(current_user, "is_admin", False):
                        project.project_user_id = getattr(current_user, "id", None)
                        updated = True
                if is_private is not None and (getattr(current_user, "is_admin", False) or project.project_user_id == getattr(current_user, "id", None)):
                    project.project_is_private = is_private
                    updated = True

                if updated:
                    await session.commit()
                await session.refresh(project)
                return project, "ok"

            if not create_if_missing or current_user is None:
                return None, "missing"

            project = Project(
                project_id=project_id,
                project_user_id=getattr(current_user, "id", None),
                project_is_private=is_private if is_private is not None else True,
            )
            session.add(project)
            await session.commit()
            await session.refresh(project)
            return project, "created"

    async def get_all_projects(self, current_user, page: int = 1, page_size: int = 10):
        async with self.db_client() as session:
            count_query = select(func.count()).select_from(Project)
            data_query = select(Project)

            if current_user and not getattr(current_user, "is_admin", False):
                visibility_filter = or_(
                    Project.project_is_private.is_(False),
                    Project.project_user_id == getattr(current_user, "id", None)
                )
                count_query = count_query.where(visibility_filter)
                data_query = data_query.where(visibility_filter)

            total_documents = await session.execute(count_query)
            total_documents = total_documents.scalar_one()

            total_pages = total_documents // page_size
            if total_documents % page_size > 0:
                total_pages += 1

            paged_query = data_query.offset((page - 1) * page_size).limit(page_size)
            projects = await session.execute(paged_query)
            projects = projects.scalars().all()

            return projects, total_pages
