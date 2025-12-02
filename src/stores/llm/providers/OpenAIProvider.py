from ..LLMInterface import LLMInterface
from ..LLMEnums import OpenAIEnums
from openai import OpenAI
import logging
import httpx
from typing import List, Union


class OpenAIProvider(LLMInterface):

    def __init__(self, api_key: str, api_url: str=None,
                       default_input_max_characters: int=1000,
                       default_generation_max_output_tokens: int=1000,
                       default_generation_temperature: float=0):
        
        self.api_key = api_key
        self.api_url = api_url

        self.default_input_max_characters = default_input_max_characters
        self.default_generation_max_output_tokens = default_generation_max_output_tokens
        self.default_generation_temperature = default_generation_temperature

        self.generation_model_id = None

        self.embedding_model_id = None
        self.embedding_size = None

        self.client = OpenAI(
            api_key = self.api_key,
            base_url = self.api_url if self.api_url and len(self.api_url) else None,
            http_client=httpx.Client(trust_env=False)
        )

        self.enums = OpenAIEnums
        self.logger = logging.getLogger(__name__)

    def set_generation_model(self, model_id: str):
        self.generation_model_id = model_id

    def set_embedding_model(self, model_id: str, embedding_size: int):
        self.embedding_model_id = model_id
        self.embedding_size = embedding_size

    def process_text(self, text: str):
        return text[:self.default_input_max_characters].strip()

    def generate_text(self, prompt: str, chat_history: list=[], max_output_tokens: int=None,
                            temperature: float = None):
        
        if not self.client:
            self.logger.error("OpenAI client was not set")
            return None

        if not self.generation_model_id:
            self.logger.error("Generation model for OpenAI was not set")
            return None
        
        max_output_tokens = max_output_tokens if max_output_tokens else self.default_generation_max_output_tokens
        # For deterministic behavior in RAG/QA flows, default to
        # temperature 0 and top_p 1 unless explicitly overridden.
        temperature = self.default_generation_temperature if temperature is None else temperature

        chat_history.append(
            self.construct_prompt(prompt=prompt, role=OpenAIEnums.USER.value)
        )

        response = self.client.chat.completions.create(
            model=self.generation_model_id,
            messages=chat_history,
            max_tokens=max_output_tokens,
            temperature=temperature,
            top_p=1.0,
        )

        if not response or not response.choices or len(response.choices) == 0 or not response.choices[0].message:
            self.logger.error("Error while generating text with OpenAI")
            return None

        message = response.choices[0].message
        content = getattr(message, "content", None)

        answer_parts = []
        reasoning_parts = []

        if isinstance(content, list):
            for part in content:
                part_type = getattr(part, "type", None)
                part_text = getattr(part, "text", None)
                part_content = getattr(part, "content", None)

                if isinstance(part, dict):
                    part_type = part.get("type", part_type)
                    if part_text is None:
                        part_text = part.get("text")
                    if part_content is None:
                        part_content = part.get("content")

                if part_text:
                    target = answer_parts
                    if part_type and isinstance(part_type, str) and part_type.lower() in ("reasoning", "analysis", "thought"):
                        target = reasoning_parts
                    target.append(part_text.strip())
                elif isinstance(part_content, str):
                    answer_parts.append(part_content.strip())
                elif isinstance(part_content, list):
                    for text_piece in self._extract_text_parts(part_content):
                        if text_piece.strip():
                            answer_parts.append(text_piece.strip())

        elif isinstance(content, str) and content.strip():
            answer_parts.append(content.strip())

        reasoning_text = getattr(message, "reasoning", None)
        if reasoning_text and isinstance(reasoning_text, str):
            reasoning_text = reasoning_text.strip()
            if reasoning_text:
                reasoning_parts.append(reasoning_text)

        output_text = getattr(message, "output_text", None)
        if output_text:
            if isinstance(output_text, str):
                stripped = output_text.strip()
                if stripped:
                    answer_parts.append(stripped)
            elif isinstance(output_text, list):
                for item in output_text:
                    if isinstance(item, str):
                        stripped = item.strip()
                        if stripped:
                            answer_parts.append(stripped)
                    elif hasattr(item, "text"):
                        text_value = getattr(item, "text")
                        if isinstance(text_value, str) and text_value.strip():
                            answer_parts.append(text_value.strip())

        combined_sections = []

        if answer_parts:
            combined_sections.append("\n".join(answer_parts).strip())

        if reasoning_parts:
            combined_sections.append("Reasoning:\n" + "\n".join(reasoning_parts).strip())

        if not combined_sections:
            refusal = getattr(message, "refusal", None)
            if refusal:
                self.logger.warning("OpenAI provider refusal: %s", refusal)
                combined_sections.append(refusal.strip())

        content = "\n\n".join(section for section in combined_sections if section)

        if not content:
            self.logger.error("OpenAI provider returned empty content")
            return None

        return content

    def _extract_text_parts(self, value):
        texts = []
        if value is None:
            return texts

        if isinstance(value, str):
            texts.append(value)
            return texts

        if isinstance(value, list):
            for item in value:
                texts.extend(self._extract_text_parts(item))
            return texts

        if isinstance(value, dict):
            text_value = value.get("text")
            if isinstance(text_value, str):
                texts.append(text_value)
            elif isinstance(text_value, list):
                texts.extend(self._extract_text_parts(text_value))

            content_value = value.get("content")
            if isinstance(content_value, str):
                texts.append(content_value)
            elif isinstance(content_value, list):
                texts.extend(self._extract_text_parts(content_value))
            return texts

        text_attr = getattr(value, "text", None)
        if isinstance(text_attr, str):
            texts.append(text_attr)

        return texts

    def generate_text_stream(self, prompt: str, chat_history: list=[], max_output_tokens: int=None,
                             temperature: float = None, collector: dict=None):

        if not self.client:
            self.logger.error("OpenAI client was not set")
            return iter(())

        if not self.generation_model_id:
            self.logger.error("Generation model for OpenAI was not set")
            return iter(())

        max_output_tokens = max_output_tokens if max_output_tokens else self.default_generation_max_output_tokens
        temperature = self.default_generation_temperature if temperature is None else temperature

        history = list(chat_history) if chat_history else []
        history.append(
            self.construct_prompt(prompt=prompt, role=OpenAIEnums.USER.value)
        )

        if collector is None:
            collector = {}

        output_collector = collector.setdefault("output", [])
        reasoning_collector = collector.setdefault("reasoning", [])

        def stream_generator():
            last_choice = None
            try:
                stream = self.client.chat.completions.create(
                    model=self.generation_model_id,
                    messages=history,
                    max_tokens=max_output_tokens,
                    temperature=temperature,
                    top_p=1.0,
                    stream=True,
                )

                for chunk in stream:
                    if not chunk or not chunk.choices:
                        continue

                    choice = chunk.choices[0]
                    last_choice = choice
                    delta = getattr(choice, "delta", None)
                    if not delta:
                        continue

                    content_value = getattr(delta, "content", None)
                    for text_piece in self._extract_text_parts(content_value):
                        output_collector.append(text_piece)
                        yield text_piece

                    reasoning_value = getattr(delta, "reasoning", None)
                    for reasoning_piece in self._extract_text_parts(reasoning_value):
                        reasoning_collector.append(reasoning_piece)

                    finish_reason = getattr(choice, "finish_reason", None)
                    if finish_reason in ("stop", "length"):
                        break

                if last_choice and getattr(last_choice, "message", None):
                    message_obj = last_choice.message
                    final_content = getattr(message_obj, "content", None)
                    for text_piece in self._extract_text_parts(final_content):
                        output_collector.append(text_piece)
                    final_reasoning = getattr(message_obj, "reasoning", None)
                    for reasoning_piece in self._extract_text_parts(final_reasoning):
                        reasoning_collector.append(reasoning_piece)

            except Exception as exc:
                self.logger.error("Error while streaming text with OpenAI: %s", exc)

        return stream_generator()


    def embed_text(self, text: Union[str, List[str]], document_type: str = None):
        
        if not self.client:
            self.logger.error("OpenAI client was not set")
            return None

        if isinstance(text, str):
            text = [text]

        if not self.embedding_model_id:
            self.logger.error("Embedding model for OpenAI was not set")
            return None

        # Ensure each input string is reasonably short for the embedding model.
        # This helps avoid backend crashes on very long inputs (e.g., GGML asserts).
        processed_inputs = [self.process_text(t or "") for t in text]

        # To avoid overloading the embedding backend (e.g., Ollama + GGML),
        # especially on large uploads, embed in small batches and concatenate.
        all_embeddings: List[List[float]] = []
        batch_size = 16

        for i in range(0, len(processed_inputs), batch_size):
            batch_inputs = processed_inputs[i:i + batch_size]
            try:
                response = self.client.embeddings.create(
                    model=self.embedding_model_id,
                    input=batch_inputs,
                )
            except Exception as exc:
                # If the Ollama / OpenAI-compatible backend crashes (e.g., GGML_ASSERT
                # or VRAM-related failures), make sure we don't crash the FastAPI app.
                self.logger.error(
                    "Error while embedding text with OpenAI-compatible backend "
                    "(model=%s): %s",
                    self.embedding_model_id,
                    exc,
                )
                return None

            if not response or not response.data:
                self.logger.error("Error while embedding text with OpenAI: empty response")
                return None

            for rec in response.data:
                if not getattr(rec, "embedding", None):
                    self.logger.error("Error while embedding text with OpenAI: missing embedding in record")
                    return None
                all_embeddings.append(rec.embedding)

        if len(all_embeddings) != len(processed_inputs):
            self.logger.error(
                "Embedding count mismatch: expected %d, got %d",
                len(processed_inputs),
                len(all_embeddings),
            )
            return None

        return all_embeddings

    def construct_prompt(self, prompt: str, role: str):
        return {
            "role": role,
            "content": prompt
        }
    


    
