from pydantic import BaseModel
from typing import Optional, List


class ProcessRequest(BaseModel):
    file_id: str = None
    chunk_size: Optional[int] = 500
    overlap_size: Optional[int] = 100
    do_reset: Optional[int] = 0
    is_private: Optional[bool] = None


class UpdateDocTypeRequest(BaseModel):
    doc_type: str


class UpdateVisibilityRequest(BaseModel):
    visibility: str
    departments: Optional[List[str]] = None
