from pydantic import BaseModel
from typing import Optional


class ProcessRequest(BaseModel):
    file_id: str = None
    chunk_size: Optional[int] = 1200
    overlap_size: Optional[int] = 250
    do_reset: Optional[int] = 0
    is_private: Optional[bool] = None


class UpdateDocTypeRequest(BaseModel):
    doc_type: str
