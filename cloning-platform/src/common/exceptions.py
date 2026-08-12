"""
exceptions.py — Custom exception hierarchy for the cloning platform.
"""


class CloningPlatformError(Exception):
    """Base exception for all platform errors."""

    def __init__(self, message: str, resource_type: str = "", resource_id: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.resource_type = resource_type
        self.resource_id = resource_id

    def to_dict(self) -> dict:
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
        }


class SubscriberNotFoundError(CloningPlatformError):
    """Raised when a subscriber record cannot be found."""


class EnvironmentAlreadyExistsError(CloningPlatformError):
    """Raised when the target environment name is already taken."""


class ProvisioningError(CloningPlatformError):
    """Raised when a resource provisioning step fails."""


class SourceResourceNotFoundError(CloningPlatformError):
    """Raised when the source AWS resource does not exist."""


class HealthCheckError(CloningPlatformError):
    """Raised when a cloned resource fails the health check."""


class ConfigurationError(CloningPlatformError):
    """Raised when required configuration is missing or invalid."""


class StateManagerError(CloningPlatformError):
    """Raised when a DynamoDB state operation fails."""


class ValidationError(CloningPlatformError):
    """Raised when input validation fails."""


class RetryExhaustedError(CloningPlatformError):
    """Raised when all retry attempts have been exhausted."""
