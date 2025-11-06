from pydantic import BaseModel
from typing import Optional

class PushRequest(BaseModel):
    do_reset: Optional[int] = 0

class SearchRequest(BaseModel):
    text: str
    limit: Optional[int] = 5
    stream: Optional[bool] = False
    conversation_id: Optional[int] = None
    model: Optional[str] = None

class SummarizeRequest(BaseModel):
    file_id: Optional[str] = None
    max_chunks: Optional[int] = 20
    max_output_tokens: Optional[int] = None
    focus: Optional[str] = None
