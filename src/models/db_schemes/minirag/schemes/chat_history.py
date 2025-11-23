from .minirag_base import SQLAlchemyBase
from sqlalchemy import Column, Integer, Text, DateTime, func, ForeignKey, String, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB

class ChatHistory(SQLAlchemyBase):

    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    conversation_id = Column(Integer, ForeignKey("chat_conversations.conversation_id"), nullable=False, index=True)
    prompt = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    response_time_ms = Column(Integer, nullable=True)
    model_key = Column(String, nullable=True)
    doc_types = Column(JSONB, nullable=True)

    # Optional quality and retrieval metadata
    rating = Column(Integer, nullable=True)  # 1-5 stars or similar scale
    is_helpful = Column(Boolean, nullable=True)
    fallback_used = Column(Boolean, nullable=True)
    retrieved_chunks = Column(Integer, nullable=True)
    retrieved_doc_types = Column(JSONB, nullable=True)
    retrieved_asset_ids = Column(JSONB, nullable=True)

    # Persisted list of resources (RAG evidence) associated with this
    # exchange so that the frontend can re-display them when loading
    # conversation history. Each item is expected to mirror the
    # structure of the `sources` list returned at answer time
    # (file_name, location, page, excerpt_index, snippet, ...).
    resources = Column(JSONB, nullable=True)

    user = relationship("User", back_populates="chat_history")
    conversation = relationship("ChatConversation", back_populates="history")
