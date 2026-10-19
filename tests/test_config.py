from aegisflow.config import (
    CHAT_MODEL,
    EMBEDDING_MODEL,
    MODEL_CONTEXT_SIZE,
    OLLAMA_BASE_URL,
)


def test_default_model_configuration() -> None:
    assert CHAT_MODEL == "gemma3:4b"
    assert EMBEDDING_MODEL == "nomic-embed-text:latest"
    assert MODEL_CONTEXT_SIZE == 4096
    assert OLLAMA_BASE_URL == "http://localhost:11434"
