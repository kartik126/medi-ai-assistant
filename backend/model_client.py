from contextlib import contextmanager
import hashlib
import json
import math
from threading import Lock
from urllib.parse import urlparse
import httpx
from backend.errors import AppError
from backend.citations import ANSWER_SCHEMA


class OllamaModels:
    def __init__(self, settings, transport=None):
        self.settings = settings
        if settings.chat_provider != "ollama":
            raise AppError("unsupported_provider", "Only the Ollama fallback is implemented. MLX compatibility could not be tested.", 503)
        if urlparse(settings.ollama_base_url).hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("Model endpoint must be local; hosted inference is not enabled")
        self.client = httpx.Client(base_url=settings.ollama_base_url, timeout=settings.model_timeout_seconds,
                                   transport=transport, trust_env=False)
        self._lock = Lock()

    def close(self):
        self.client.close()

    @contextmanager
    def serialized(self):
        if not self._lock.acquire(timeout=5):
            raise AppError("model_busy", "The local model is busy. Retry when the current request finishes.", 503)
        try:
            yield
        finally:
            self._lock.release()

    def _request(self, method, path, payload=None):
        try:
            response = self.client.request(method, path, json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as exc:
            raise AppError("model_timeout", "The local model timed out. Retry with a smaller selection.", 504) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise AppError("model_unavailable", "Local model request failed. Check Ollama and installed model tags.", 503) from exc

    def identity(self):
        tags = self._request("GET", "/api/tags").get("models", [])
        match = next((m for m in tags if m.get("name") == self.settings.embedding_model or m.get("model") == self.settings.embedding_model), None)
        if not match or not match.get("digest"):
            raise AppError("embedding_missing", "Install the configured embedding model in Ollama.", 503)
        # Query formatting is part of the embedding-space contract.
        instruction = self.query_instruction()
        return f"{self.settings.embedding_model}@{match['digest']}:query-{hashlib.sha256(instruction.encode()).hexdigest()[:12]}"

    def query_instruction(self):
        return "Instruct: Retrieve document passages that answer the question.\nQuery: " if self.settings.embedding_model.startswith("qwen3-embedding") else ""

    def readiness(self):
        data = self._request("GET", "/api/tags")
        tags = {m.get("name") for m in data.get("models", [])} | {m.get("model") for m in data.get("models", [])}
        return {"ready": self.settings.chat_model in tags and self.settings.embedding_model in tags,
                "chat_installed": self.settings.chat_model in tags, "embedding_installed": self.settings.embedding_model in tags}

    def embed(self, texts, query=False):
        prepared = [self.query_instruction() + t for t in texts] if query else texts
        result = self._request("POST", "/api/embed", {
            "model": self.settings.embedding_model, "input": prepared,
            "truncate": False, "keep_alive": 0,
        })
        vectors = result.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise AppError("invalid_embeddings", "Embedding provider returned an invalid batch.", 503)
        normalized, dimension = [], None
        for vector in vectors:
            if not isinstance(vector, list) or not vector or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vector):
                raise AppError("invalid_embeddings", "Embedding vector is empty or non-finite.", 503)
            dimension = dimension or len(vector)
            norm = math.sqrt(sum(v*v for v in vector))
            if len(vector) != dimension or norm == 0 or not math.isfinite(norm):
                raise AppError("invalid_embeddings", "Embedding dimensions or norm are invalid.", 503)
            normalized.append([v / norm for v in vector])
        return normalized

    def generate_with_schema(self, messages, schema):
        return self.generate(messages, response_schema=schema)

    def select_evidence(self, messages, schema):
        """Choose server-owned excerpts; no free-form medical claims."""
        return self.generate(messages, response_schema=schema)

    def summarize_evidence(self, messages, schema):
        return self.generate(messages, response_schema=schema)

    def check_summary(self, messages, schema):
        return self.generate(messages, response_schema=schema)

    def generate(self, messages, response_schema=None):
        # A UTF-8 byte count is a deliberately conservative token upper-bound
        # heuristic for this text-only path; provider token counts are also checked.
        budget = sum(len(m["content"].encode("utf-8")) + 64 for m in messages) + 1024
        if budget + self.settings.max_output_tokens > self.settings.model_context_tokens:
            raise AppError("context_limit", "Evidence exceeds the configured model context budget. Reduce context size.")
        data = self._request("POST", "/api/chat", {
            "model": self.settings.chat_model, "messages": messages, "stream": False,
            "format": response_schema or ANSWER_SCHEMA, "keep_alive": "2m",
            "options": {"temperature": 0, "num_predict": self.settings.max_output_tokens,
                        "num_ctx": self.settings.model_context_tokens},
        })
        if data.get("done_reason") == "length":
            raise ValueError("Generation was truncated")
        count = data.get("prompt_eval_count", 0)
        if count + self.settings.max_output_tokens >= self.settings.model_context_tokens:
            raise ValueError("Prompt may have filled the context window")
        content = data.get("message", {}).get("content")
        if not isinstance(content, str):
            raise ValueError("Provider returned no text")
        return content
