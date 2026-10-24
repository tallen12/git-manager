import pytest
from pydantic import ValidationError

from git_manager.approvals import Actor, ActorType, ApiToken, Principal, Scope, TokensFile
from git_manager.approvals.models import MIN_TOKEN_LENGTH


def test_actor_serializes_with_the_audit_log_names() -> None:
    actor = Actor(type=ActorType.MCP_AGENT, identity="review-bot")

    assert actor.model_dump(mode="json") == {"type": "mcp-agent", "identity": "review-bot"}


def test_actor_needs_an_identity() -> None:
    with pytest.raises(ValidationError):
        Actor(type=ActorType.HUMAN_CLI, identity="")


def test_a_principal_allows_only_its_own_scopes() -> None:
    principal = Principal(name="mcp-agent", scopes=frozenset({Scope.READ, Scope.OPERATE}))

    assert principal.allows(Scope.OPERATE)
    assert not principal.allows(Scope.APPROVE)


def token(name: str, value: str, *scopes: Scope) -> dict[str, object]:
    return {"name": name, "token": value, "scopes": [str(scope) for scope in scopes]}


def test_tokens_must_be_long_and_have_a_scope() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        ApiToken.model_validate(token("x", "a" * (MIN_TOKEN_LENGTH - 1), Scope.READ))
    with pytest.raises(ValidationError, match="at least 1"):
        ApiToken.model_validate(token("x", "a" * MIN_TOKEN_LENGTH))


def test_unknown_scopes_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ApiToken.model_validate({"name": "x", "token": "a" * 40, "scopes": ["admin"]})


def test_token_names_must_be_unique() -> None:
    entries = [token("ops", "a" * 40, Scope.READ), token("ops", "b" * 40, Scope.READ)]

    with pytest.raises(ValidationError, match="token names must be unique: ops"):
        TokensFile.model_validate({"tokens": entries})


def test_token_values_must_be_unique_and_are_never_quoted() -> None:
    value = "c" * 40
    entries = [token("one", value, Scope.READ), token("two", value, Scope.OPERATE)]

    with pytest.raises(ValidationError) as caught:
        TokensFile.model_validate({"tokens": entries})

    # Only the message: pydantic's own text also quotes the input, which load_tokens drops.
    message = caught.value.errors()[0]["msg"]
    assert "share a token value" in message
    assert value not in message
