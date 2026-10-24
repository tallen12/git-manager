from pathlib import Path

import pytest
from pydantic import SecretStr

from git_manager.approvals import (
    SOCKET_PRINCIPAL,
    ApiToken,
    Authenticator,
    Principal,
    Scope,
    TokenAuthenticator,
    TokensFile,
    TokensFileError,
    TrustedAuthenticator,
    load_tokens,
)

OPERATOR = "operator-token-0123456789abcdef0123"
AGENT = "mcp-agent-token-0123456789abcdef012"


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_load_tokens_reads_names_and_scopes(tmp_path: Path) -> None:
    path = write(
        tmp_path / "tokens.yaml",
        f"tokens:\n  - name: operator\n    token: {OPERATOR}\n"
        "    scopes: [read, operate, approve]\n",
    )

    tokens = load_tokens(path)

    assert [entry.name for entry in tokens.tokens] == ["operator"]
    assert tokens.tokens[0].scopes == frozenset(Scope)
    assert tokens.tokens[0].token.get_secret_value() == OPERATOR


def test_a_missing_tokens_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(TokensFileError, match="cannot read the tokens file"):
        load_tokens(tmp_path / "absent.yaml")


def test_invalid_yaml_is_reported_without_quoting_the_file(tmp_path: Path) -> None:
    path = write(tmp_path / "tokens.yaml", f"tokens: [{{token: {OPERATOR}\n")

    with pytest.raises(TokensFileError, match="not valid YAML") as caught:
        load_tokens(path)

    assert OPERATOR not in str(caught.value)


def test_validation_errors_name_the_field_but_never_the_token(tmp_path: Path) -> None:
    short = "too-short-secret"
    path = write(
        tmp_path / "tokens.yaml", f"tokens:\n  - name: x\n    token: {short}\n    scopes: []\n"
    )

    with pytest.raises(TokensFileError) as caught:
        load_tokens(path)

    message = str(caught.value)
    assert "tokens.0.token" in message
    assert "tokens.0.scopes" in message
    assert short not in message


@pytest.fixture
def authenticator_under_test() -> TokenAuthenticator:
    return TokenAuthenticator(
        TokensFile(
            tokens=(
                ApiToken(name="operator", token=SecretStr(OPERATOR), scopes=frozenset(Scope)),
                ApiToken(
                    name="mcp-agent",
                    token=SecretStr(AGENT),
                    scopes=frozenset({Scope.READ, Scope.OPERATE}),
                ),
            )
        )
    )


def test_a_known_token_authenticates_as_its_entry(
    authenticator_under_test: TokenAuthenticator,
) -> None:
    authenticator: Authenticator = authenticator_under_test

    assert authenticator.authenticate(AGENT) == Principal(
        name="mcp-agent", scopes=frozenset({Scope.READ, Scope.OPERATE})
    )


@pytest.mark.parametrize("token", [None, "", "operator", OPERATOR + "x", OPERATOR[:-1]])
def test_a_missing_or_unknown_token_does_not_authenticate(
    authenticator_under_test: TokenAuthenticator, token: str | None
) -> None:
    assert authenticator_under_test.authenticate(token) is None


@pytest.mark.parametrize("token", [None, "anything"])
def test_the_socket_authenticator_trusts_every_request(token: str | None) -> None:
    authenticator: Authenticator = TrustedAuthenticator()

    principal = authenticator.authenticate(token)

    assert principal == SOCKET_PRINCIPAL
    assert principal is not None
    assert all(principal.allows(scope) for scope in Scope)
