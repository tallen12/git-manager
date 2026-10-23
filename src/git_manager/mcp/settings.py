"""MCP server settings (the ``mcp`` section)."""

from pydantic import BaseModel, ConfigDict, Field


class McpSettings(BaseModel):
    """How the MCP server presents itself."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(
        default="git-manager", description="Server name shown to MCP clients. [env: GM_MCP__NAME]"
    )
    # Read once MCP is mounted on the REST server (M4); stdio has no path.
    path: str = Field(
        default="/mcp",
        pattern=r"^/",
        description="Where MCP mounts on the REST server (M4). [env: GM_MCP__PATH]",
    )
