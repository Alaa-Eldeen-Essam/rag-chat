from .minirag_base import SQLAlchemyBase
from sqlalchemy import Column, Integer, Text, DateTime, func, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship


class SummaryRecord(SQLAlchemyBase):

    __tablename__ = "summaries"

    summary_id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.project_id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey("assets.asset_id"), nullable=True, index=True)

    request_payload = Column(JSONB, nullable=False, default=dict)
    chunk_ids = Column(JSONB, nullable=True)
    chunk_count = Column(Integer, nullable=False)

    summary_text = Column(Text, nullable=False)
    prompt_text = Column(Text, nullable=True)
    max_output_tokens = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project = relationship("Project", back_populates="summaries")
    user = relationship("User", back_populates="summaries")
    asset = relationship("Asset", back_populates="summaries")
