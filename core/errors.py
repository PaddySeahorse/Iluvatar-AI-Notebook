"""Custom exception hierarchy for structured API error responses (ISSUE-009).

Every application-level error inherits from :class:`AppError` and carries a
machine-readable ``error_code`` plus an HTTP ``status_code``.  The Flask error
handler (registered in :mod:`core.routes`) converts any :class:`AppError`
subclass into a consistent JSON response.
"""


class AppError(Exception):
    """Base class for all application-level errors.

    Attributes:
        message  -- human-readable description
        status_code -- HTTP status code to return
        error_code  -- machine-readable short identifier (e.g. 'KERNEL_DEAD')
    """
    status_code: int = 500
    error_code: str = 'INTERNAL_ERROR'

    def __init__(self, message: str, error_code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if error_code is not None:
            self.error_code = error_code
        if status_code is not None:
            self.status_code = status_code

    def to_dict(self) -> dict:
        return {
            'error': True,
            'error_code': self.error_code,
            'message': self.message,
        }


class KernelError(AppError):
    """Raised when the Python kernel process cannot be reached or misbehaves."""
    status_code = 503
    error_code = 'KERNEL_ERROR'


class FileStorageError(AppError):
    """Raised for notebook file I/O problems."""
    status_code = 500
    error_code = 'FILE_ERROR'


class UpstreamAPIError(AppError):
    """Raised when a call to the external AI API fails."""
    status_code = 502
    error_code = 'UPSTREAM_API_ERROR'
