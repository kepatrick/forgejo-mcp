from contextvars import ContextVar, Token

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("user_id", default=None)
_invocation_id: ContextVar[str | None] = ContextVar("invocation_id", default=None)


def request_id() -> str | None:
    return _request_id.get()


def user_id() -> str | None:
    return _user_id.get()


def invocation_id() -> str | None:
    return _invocation_id.get()


def set_request_id(value: str) -> Token[str | None]:
    return _request_id.set(value)


def set_user_id(value: str) -> Token[str | None]:
    return _user_id.set(value)


def set_invocation_id(value: str) -> Token[str | None]:
    return _invocation_id.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id.reset(token)


def reset_user_id(token: Token[str | None]) -> None:
    _user_id.reset(token)


def reset_invocation_id(token: Token[str | None]) -> None:
    _invocation_id.reset(token)
