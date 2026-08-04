class ApplicationError(Exception):
    """Base class for expected application-layer failures."""


class AuthenticationFailed(ApplicationError):
    pass


class NotFound(ApplicationError):
    pass


class Conflict(ApplicationError):
    pass


class InvalidOperation(ApplicationError):
    pass


class Gone(ApplicationError):
    pass


class ValidationFailed(ApplicationError):
    pass


class ExternalServiceUnavailable(ApplicationError):
    pass


class ConfigurationUnavailable(ApplicationError):
    pass
