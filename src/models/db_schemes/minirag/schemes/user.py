from .minirag_base import SQLAlchemyBase
from sqlalchemy import Column, Integer, String, Boolean, DateTime, func
from sqlalchemy.orm import relationship
from sqlalchemy import Index

class User(SQLAlchemyBase):

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    is_admin = Column(Boolean, nullable=False, default=False)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_login = Column(DateTime(timezone=True), nullable=True)

    projects = relationship("Project", back_populates="user")
    assets = relationship("Asset", back_populates="user")
    chat_history = relationship("ChatHistory", back_populates="user")
    conversations = relationship("ChatConversation", back_populates="user")
    summaries = relationship("SummaryRecord", back_populates="user")

    __table_args__ = (
        Index('ix_users_is_admin', is_admin),
    )
