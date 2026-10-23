import pytest
from pydantic import ValidationError

from git_manager.mcp.settings import McpSettings


def test_defaults() -> None:
    assert McpSettings() == McpSettings(name="git-manager", path="/mcp")


def test_path_must_be_absolute() -> None:
    with pytest.raises(ValidationError):
        McpSettings(path="mcp")
