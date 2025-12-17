from pydantic import BaseModel
from typing import Optional, List

class PushRequest(BaseModel):
    do_reset: Optional[int] = 0
    asset_name: Optional[str] = None

class SearchRequest(BaseModel):
    text: str
    limit: Optional[int] = 5
    stream: Optional[bool] = True
    conversation_id: Optional[int] = None
    model: Optional[str] = None
    asset_id: Optional[int] = None
    asset_ids: Optional[List[int]] = None
    doc_type: Optional[str] = None
    mode: Optional[str] = "rag"

class SummarizeRequest(BaseModel):
    file_id: Optional[str] = None
    max_chunks: Optional[int] = 0
    max_output_tokens: Optional[int] = None
    focus: Optional[str] = None
    stream: Optional[bool] = True
    model: Optional[str] = None
    output_lang: Optional[str] = None


class ConversationUpdateRequest(BaseModel):
    title: Optional[str] = None
    is_pinned: Optional[bool] = None


class DeleteSummariesRequest(BaseModel):
    summary_ids: List[int]
