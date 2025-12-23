from typing import Optional

from helpers.config import Settings
from .SearchProviderInterface import SearchProviderInterface
from .providers import ElasticsearchProvider


class SearchProviderFactory:
    def __init__(self, config: Settings):
        self.config = config

    def create(self) -> Optional[SearchProviderInterface]:
        if not self.config.ELASTICSEARCH_URL:
            return None

        return ElasticsearchProvider(
            base_url=self.config.ELASTICSEARCH_URL,
            index_prefix=self.config.ELASTICSEARCH_INDEX_PREFIX or "minirag",
        )


