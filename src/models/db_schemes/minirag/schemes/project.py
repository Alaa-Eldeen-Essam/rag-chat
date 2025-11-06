from .minirag_base import SQLAlchemyBase
from sqlalchemy import Column, Integer, DateTime, func, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy import Index
import uuid

class Project(SQLAlchemyBase):

    __tablename__ = "projects"

    project_id = Column(Integer, primary_key=True, autoincrement=True)
    project_uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)

    project_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    project_is_private = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    chunks = relationship("DataChunk", back_populates="project")
    assets = relationship("Asset", back_populates="project")
    user = relationship("User", back_populates="projects")

    __table_args__ = (
        Index('ix_project_user_id', project_user_id),
        Index('ix_project_is_private', project_is_private),
    )
