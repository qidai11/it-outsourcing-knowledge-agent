from __future__ import annotations


class RagflowError(RuntimeError):
    """Base error raised by the RAGFlow adapter."""


class RagflowHttpError(RagflowError):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"RAGFlow HTTP {status_code}: {message}")


class RagflowApiError(RagflowError):
    def __init__(self, code: int | str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"RAGFlow API code={code}: {message}")


class RagflowProtocolError(RagflowError):
    """RAGFlow returned a successful response with an unexpected shape."""


class RagflowConfigurationError(RagflowError):
    """The adapter cannot perform an operation with its current configuration."""


class RagflowProjectIsolationError(RagflowError):
    """A dataset or document violates the application project boundary."""
