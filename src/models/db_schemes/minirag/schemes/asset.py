from .minirag_base import SQLAlchemyBase
from sqlalchemy import Column, Integer, DateTime, func, String, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy import Index
import uuid

class Asset(SQLAlchemyBase):

    __tablename__ = "assets"

    asset_id = Column(Integer, primary_key=True, autoincrement=True)
    asset_uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)

    asset_type = Column(String, nullable=False)
    asset_name = Column(String, nullable=False)
    asset_size = Column(Integer, nullable=False)
    asset_config = Column(JSONB, nullable=True)
    asset_document_type = Column(String, nullable=False, default="general")

    asset_project_id = Column(Integer, ForeignKey("projects.project_id"), nullable=False)
    asset_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    asset_is_private = Column(Boolean, nullable=False, default=True)
    # Visibility: "private" | "department" | "global"
    asset_visibility = Column(String, nullable=False, default="private")
    # Department for department-level visibility
    asset_department = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    project = relationship("Project", back_populates="assets")
    chunks = relationship("DataChunk", back_populates="asset")
    user = relationship("User", back_populates="assets")
    summaries = relationship("SummaryRecord", back_populates="asset")

    __table_args__ = (
        Index('ix_asset_project_id', asset_project_id),
        Index('ix_asset_type', asset_type),
        Index('ix_asset_document_type', asset_document_type),
        Index('ix_asset_user_id', asset_user_id),
        Index('ix_asset_is_private', asset_is_private),
        Index('ix_asset_visibility', asset_visibility),
        Index('ix_asset_department', asset_department),
    )
