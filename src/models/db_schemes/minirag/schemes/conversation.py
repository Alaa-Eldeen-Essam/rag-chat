from .minirag_base import SQLAlchemyBase
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from sqlalchemy import Index


class ChatConversation(SQLAlchemyBase):

    __tablename__ = "chat_conversations"

    conversation_id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    conversation_title = Column(String, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    user = relationship("User", back_populates="conversations")
    history = relationship("ChatHistory", back_populates="conversation", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_chat_conversations_user_title", conversation_user_id, conversation_title),
    )
