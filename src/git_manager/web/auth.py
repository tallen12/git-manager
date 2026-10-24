"""Scope checks for REST routes: who a request acts as, and whether it may."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.params import Depends as DependsParam
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from git_manager.approvals import Authenticator, Principal, Scope

# auto_error=False: a missing token is answered below, with the same 401 as a wrong one.
_BEARER = HTTPBearer(auto_error=False)


class Access:
    """Builds the dependency each route declares for the scope it needs.

    One per listener: the HTTP listener checks tokens, the Unix socket trusts its callers.
    """

    def __init__(self, authenticator: Authenticator) -> None:
        self._authenticator = authenticator

    def requires(self, scope: Scope) -> DependsParam:
        """A route dependency that admits a request only if its principal holds ``scope``.

        Answers ``401`` without a valid token and ``403`` when the token lacks ``scope``.
        """

        def principal(
            credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER)],
        ) -> Principal:
            token = None if credentials is None else credentials.credentials
            found = self._authenticator.authenticate(token)
            if found is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="missing or invalid API token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            if not found.allows(scope):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"token {found.name!r} lacks the {scope} scope",
                )
            return found

        # The class itself: ``fastapi.Depends`` is typed as returning ``Any``.
        return DependsParam(dependency=principal)
