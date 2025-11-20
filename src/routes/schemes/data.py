from pydantic import BaseModel
from typing import Optional


class ProcessRequest(BaseModel):
    file_id: str = None
    chunk_size: Optional[int] = 400
    overlap_size: Optional[int] = 50
    do_reset: Optional[int] = 0
    is_private: Optional[bool] = None


class UpdateDocTypeRequest(BaseModel):
    doc_type: str
