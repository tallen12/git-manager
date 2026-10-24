"""API authentication: the tokens file over HTTP, and full trust over the Unix socket."""

import hmac
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError
from ruamel.yaml import YAML, YAMLError

from git_manager.approvals.models import Principal, Scope, TokensFile
from git_manager.errors import OperationError

# Requests over the socket: its 0660 mode and gm-admin group already decided who may ask.
SOCKET_PRINCIPAL = Principal(name="socket", scopes=frozenset(Scope))


class TokensFileError(OperationError):
    """The tokens file is missing, unreadable or invalid."""


def _issues(error: ValidationError) -> str:
    # Locations and messages only: pydantic's own text quotes the input, a token among it.
    return "; ".join(
        f"{'.'.join(str(part) for part in issue['loc']) or '(file)'}: {issue['msg']}"
        for issue in error.errors()
    )


def load_tokens(path: Path) -> TokensFile:
    """Read and validate the tokens file at ``path``.

    Raises ``TokensFileError`` naming the problem but never a token's value.
    """
    try:
        data: object = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    except OSError as error:
        msg = f"cannot read the tokens file {path}: {error.strerror or error}"
        raise TokensFileError(msg) from error
    except YAMLError:
        # The parser's message can quote the offending line, which may hold a token.
        msg = f"the tokens file {path} is not valid YAML"
        raise TokensFileError(msg) from None
    try:
        return TokensFile.model_validate(data)
    except ValidationError as error:
        msg = f"invalid tokens file {path}: {_issues(error)}"
        raise TokensFileError(msg) from None


@dataclass(frozen=True, slots=True)
class TokenAuthenticator:
    """``Authenticator`` for HTTP: a request needs a token from the tokens file."""

    tokens: TokensFile

    def authenticate(self, token: str | None) -> Principal | None:
        """The principal whose token matches, compared in constant time."""
        if token is None:
            return None
        given = token.encode()
        found = None
        # Every entry is compared, so timing does not reveal which one matched.
        for entry in self.tokens.tokens:
            if hmac.compare_digest(entry.token.get_secret_value().encode(), given):
                found = entry
        if found is None:
            return None
        return Principal(name=found.name, scopes=found.scopes)


@dataclass(frozen=True, slots=True)
class TrustedAuthenticator:
    """``Authenticator`` for the Unix socket: every request acts as ``principal``."""

    principal: Principal = SOCKET_PRINCIPAL

    def authenticate(self, token: str | None) -> Principal:
        """Always ``principal``; the socket's file mode is the access check."""
        return self.principal
