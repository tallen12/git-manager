# Git Manager

A containerized service that keeps long-lived git branches rebased on their base branch.
Conflicts are resolved with Claude CLI under strict limits, every result is checked by the
repo's own tests, and anything an AI changed waits for human approval before it is pushed.
Keeping branches rebased is the first operation; more git operations may follow.

- Spec and delivery plan: [`design-docs/spec.md`](design-docs/spec.md)
- Conventions for humans and coding agents: [`AGENTS.md`](AGENTS.md)

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and [just](https://just.systems/).

```sh
just setup     # install locked dependencies (Python 3.14 is fetched by uv)
just check     # format check, lint, type check, tests
just coverage  # tests with branch coverage
just serve --config config.yaml  # REST on http://127.0.0.1:8765, GET /healthz
just mcp --config config.yaml    # MCP over stdio
just diagrams  # re-render design-docs/images/*.dot (needs Graphviz)
```

The CLI is `git-manager`; once installed on `PATH`, git also runs it as `git manager`.
Every command runs either in-process from a config file (local mode) or through a running
daemon's REST API (API mode). Pick one target with flags, which work on every command,
or the matching `GM_TARGET__*` variables:

```sh
just cli doctor --config config.yaml                               # local mode
GM_TARGET__TOKEN=... just cli doctor --url http://127.0.0.1:8765   # API mode over HTTP
just cli doctor --socket /run/git-manager/api.sock                 # API mode over the socket
GM_TARGET__CONFIG=config.yaml just cli doctor                      # target from the environment
```

`serve` and `mcp stdio` take the same target, so `just mcp --url ...` bridges MCP over
stdio to a running daemon. The image sets `GM_TARGET__CONFIG=/etc/git-manager/config.yaml`;
mount a config file there.

`.claude/skills` is a symlink to `.agents/skills`. Clone with `core.symlinks=true` (the
default on macOS and Linux) so Claude Code can load the shared skills.

## Status

Project skeleton only: the health operation in local and API mode, over the CLI, REST and
MCP. Milestones M1 to M5 in
the spec describe what comes next.
