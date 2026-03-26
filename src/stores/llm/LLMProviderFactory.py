
from .LLMEnums import LLMEnums
from .providers import OpenAIProvider


class LLMProviderFactory:
    def __init__(self, config):
        self.config = config

    def _create_openai_client(self, api_url: str | None):
        return OpenAIProvider(
            api_key=self.config.OPENAI_API_KEY,
            api_url=api_url or self.config.OPENAI_API_URL,
            default_input_max_characters=self.config.INPUT_DAFAULT_MAX_CHARACTERS,
            default_generation_max_output_tokens=self.config.GENERATION_DAFAULT_MAX_TOKENS,
            default_generation_temperature=self.config.GENERATION_DAFAULT_TEMPERATURE,
        )

    def create_generation_client(self):
        """
        Create an LLM client for generation/chat, preferring the
        role-specific Ollama chat endpoint when available.
        """
        if self.config.GENERATION_BACKEND == LLMEnums.OPENAI.value:
            api_url = (
                self.config.GENERATION_API_URL
                or getattr(self.config, "OLLAMA_CHAT_API_URL", None)
            )
            return self._create_openai_client(api_url)
        return None

    def create_embedding_client(self):
        """
        Create an LLM client for embeddings, preferring the
        role-specific Ollama embedding endpoint when available.
        """
        if self.config.EMBEDDING_BACKEND == LLMEnums.OPENAI.value:
            api_url = (
                self.config.EMBEDDING_API_URL
                or getattr(self.config, "OLLAMA_EMBED_API_URL", None)
            )
            return self._create_openai_client(api_url)
        return None

    def create(self, provider: str, api_url: str | None = None):
        """
        Backwards-compatible generic factory. Prefer using
        create_generation_client / create_embedding_client.
        """
        if provider == LLMEnums.OPENAI.value:
            return self._create_openai_client(api_url)
        return None
