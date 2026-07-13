class RuntimeFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TimeoutFailure(RuntimeFailure):
    pass


class PermissionFailure(RuntimeFailure):
    pass


class ValidationFailure(RuntimeFailure):
    pass


class ProviderFailure(RuntimeFailure):
    retryable = False


class ProviderTemporaryFailure(ProviderFailure):
    retryable = True


class ProviderRateLimitFailure(ProviderTemporaryFailure):
    pass


class ProviderAuthenticationFailure(ProviderFailure):
    pass


class ProviderContentRejected(ProviderFailure):
    pass


class CancelledFailure(RuntimeFailure):
    pass
