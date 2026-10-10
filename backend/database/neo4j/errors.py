"""Safe public errors: never include driver exception text, Cypher or parameter values."""

from neo4j.exceptions import AuthError, Neo4jError, ServiceUnavailable, SessionExpired


class GraphDatabaseError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class GraphConfigurationError(GraphDatabaseError):
    def __init__(self) -> None:
        super().__init__("CONFIGURATION", "Invalid or missing Neo4j environment configuration")


def translate_error(error: Exception) -> GraphDatabaseError:
    if isinstance(error, GraphDatabaseError):
        return error
    if isinstance(error, AuthError):
        return GraphDatabaseError("AUTHENTICATION", "Neo4j authentication failed")
    if isinstance(error, TimeoutError):
        return GraphDatabaseError("TIMEOUT", "Neo4j operation timed out", retryable=True)
    if isinstance(error, (ServiceUnavailable, SessionExpired, OSError)):
        return GraphDatabaseError("UNAVAILABLE", "Neo4j connection unavailable", retryable=True)
    if isinstance(error, Neo4jError):
        code = error.code or ""
        if "Security" in code:
            return GraphDatabaseError("FORBIDDEN", "Neo4j operation is not permitted")
        if "TimedOut" in code or "Timeout" in code:
            return GraphDatabaseError("TIMEOUT", "Neo4j transaction timed out", retryable=True)
        return GraphDatabaseError(
            "QUERY_FAILED", "Neo4j query failed", retryable=error.is_retryable()
        )
    return GraphDatabaseError("DRIVER_ERROR", "Neo4j operation failed")
