from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class SearchProviderInterface(ABC):
    @abstractmethod
    async def connect(self) -> None:
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        ...

    @abstractmethod
    def get_index_name(self, project_id: int) -> str:
        ...

    @abstractmethod
    async def index_documents(
        self,
        index_name: str,
        documents: List[Dict[str, Any]],
    ) -> None:
        ...

    @abstractmethod
    async def search(
        self,
        index_name: str,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        size: int = 10,
    ) -> List[Dict[str, Any]]:
        ...

