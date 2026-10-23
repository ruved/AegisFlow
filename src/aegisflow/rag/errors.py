"""Expected failures at the RAG service and local dependency boundaries."""


class RAGServiceError(Exception):
    """Base class for expected RAG service failures."""


class OllamaUnavailableError(RAGServiceError):
    """Ollama could not be reached or returned a server error."""


class OllamaTimeoutError(RAGServiceError):
    """An Ollama request exceeded its configured socket timeout."""


class OllamaConfigurationError(RAGServiceError):
    """Ollama URL or configured model is invalid for the local service."""


class OllamaResponseError(RAGServiceError):
    """Ollama returned an invalid or unsuccessful response."""


class VectorStoreUnavailableError(RAGServiceError):
    """The local Chroma store cannot be accessed."""
