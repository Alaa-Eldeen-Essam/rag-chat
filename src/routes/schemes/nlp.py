from pydantic import BaseModel, Field
from typing import Optional, List

class PushRequest(BaseModel):
    do_reset: Optional[int] = 0
    asset_name: Optional[str] = None

class SearchRequest(BaseModel):
    text: str
    limit: Optional[int] = Field(default=5, ge=1, le=50)
    stream: Optional[bool] = True
    conversation_id: Optional[int] = None
    model: Optional[str] = None
    asset_id: Optional[int] = None
    asset_ids: Optional[List[int]] = None
    doc_type: Optional[str] = None
    mode: Optional[str] = "rag"
    answer_style: Optional[str] = None  # optional hint; otherwise inferred from question
    explain_retrieval: Optional[bool] = False
    history_weight: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    ambiguity_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    force_clarification: Optional[bool] = None
    # Multihop options (used when mode="multihop")
    multihop_hops: Optional[int] = Field(default=None, ge=1, le=5)
    multihop_k: Optional[int] = Field(default=None, ge=1, le=20)
    multihop_per_hop_evidence: Optional[int] = Field(default=None, ge=1, le=20)
    multihop_temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)

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
