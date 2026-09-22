class StructuredLLMError(RuntimeError):
    """Base exception for controlled structured-LLM adapter failures."""


class StructuredLLMTransportError(StructuredLLMError):
    """Raised when the provider cannot be reached after bounded retries."""


class StructuredLLMHTTPError(StructuredLLMError):
    """Raised when the provider returns a non-success HTTP response."""


class StructuredLLMProtocolError(StructuredLLMError):
    """Raised when the provider response does not match the transport contract."""


class StructuredLLMSchemaError(StructuredLLMError):
    """Raised when structured content cannot validate against the requested schema."""
