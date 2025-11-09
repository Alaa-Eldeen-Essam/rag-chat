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
                       default_generation_temperature: float=0.1):
        
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
        temperature = temperature if temperature else self.default_generation_temperature

        chat_history.append(
            self.construct_prompt(prompt=prompt, role=OpenAIEnums.USER.value)
        )

        response = self.client.chat.completions.create(
            model = self.generation_model_id,
            messages = chat_history,
            max_tokens = max_output_tokens,
            temperature = temperature
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

                if part_text:
                    target = answer_parts
                    if part_type and part_type.lower() in ("reasoning", "analysis", "thought"):
                        target = reasoning_parts
                    target.append(part_text.strip())
                elif hasattr(part, "content") and isinstance(part.content, str):
                    answer_parts.append(part.content.strip())

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
        temperature = temperature if temperature else self.default_generation_temperature

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
                    stream=True
                )

                for chunk in stream:
                    if not chunk or not chunk.choices:
                        continue

                    choice = chunk.choices[0]
                    last_choice = choice
                    delta = getattr(choice, "delta", None)
                    if not delta:
                        continue

                    for text_piece in self._extract_text_parts(getattr(delta, "content", None)):
                        output_collector.append(text_piece)
                        yield text_piece

                    for reasoning_piece in self._extract_text_parts(getattr(delta, "reasoning", None)):
                        reasoning_collector.append(reasoning_piece)

                    finish_reason = getattr(choice, "finish_reason", None)
                    if finish_reason in ("stop", "length"):
                        break

                if last_choice and getattr(last_choice, "message", None):
                    message_obj = last_choice.message
                    for text_piece in self._extract_text_parts(getattr(message_obj, "content", None)):
                        output_collector.append(text_piece)
                    for reasoning_piece in self._extract_text_parts(getattr(message_obj, "reasoning", None)):
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
        
        response = self.client.embeddings.create(
            model = self.embedding_model_id,
            input = text,
        )

        if not response or not response.data or len(response.data) == 0 or not response.data[0].embedding:
            self.logger.error("Error while embedding text with OpenAI")
            return None

        return [ rec.embedding for rec in response.data ]

    def construct_prompt(self, prompt: str, role: str):
        return {
            "role": role,
            "content": prompt
        }
    


    
