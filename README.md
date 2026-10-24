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
just serve --config config.yaml  # REST on http://127.0.0.1:8765, GET /api/v1/healthz
just mcp --config config.yaml    # MCP over stdio
just diagrams  # re-render design-docs/images/*.dot (needs Graphviz)
```

The CLI is `git-manager`; once installed on `PATH`, git also runs it as `git manager`.
Every command runs either in-process from a config file (local mode) or through a running
daemon's REST API (API mode). Pick one target with flags, which work on every command:

```sh
just cli doctor --config config.yaml                               # local mode
GM_TARGET__TOKEN=... just cli doctor --url http://127.0.0.1:8765   # API mode over HTTP
just cli doctor --socket /run/git-manager/api.sock                 # API mode over the socket
```

`serve` and `mcp stdio` take the same target, so `just mcp --url ...` bridges MCP over
stdio to a running daemon.

## Settings

Settings have three sections: `target` (where operations run), `http` (where `serve`
listens) and `mcp` (the MCP server). Each value can come from, highest first:

1. Flags: `--config`, `--url`, `--socket`, `--plain-http`, `--http.port`, `--mcp.name`, ...
2. `GM_*` environment variables, nested with `__`: `GM_TARGET__URL`, `GM_HTTP__PORT`.
3. A `.env` file in the current directory, with the same variable names.
4. Files in the secrets directory (`/run/secrets`, or `GM_SECRETS_DIR`), one per value,
   named like the variable in lower case: `gm_target__token` holds the API token.
5. `git-manager.yaml` in the current directory (or the file `GM_SETTINGS_FILE` names).

Nested values merge across sources, except the target: the highest source that names one (`config`, `url` or `socket`) wins it, so `--socket` replaces a `url` from `git-manager.yaml`. The API token has no flag, so it never lands in shell
history.

An `http://` URL is accepted only for a loopback host, so the token is never sent
unencrypted over a network. On a network you trust, such as a compose network, set
`plain_http: allowed` (`--plain-http allowed` or `GM_TARGET__PLAIN_HTTP`). Set on its own,
it applies to any URL. Set in the same source as a URL, it applies only to that URL and
is dropped when a flag or variable replaces the URL.

Copy [`git-manager.example.yaml`](git-manager.example.yaml) to start; relative
paths in it resolve against the current directory. `git-manager.yaml` and `.env` are
ignored by git, since they may hold a token.

The image sets `GM_TARGET__CONFIG=/etc/git-manager/config.yaml` and `GM_HTTP__HOST=0.0.0.0`;
mount a config file there.

`.claude/skills` is a symlink to `.agents/skills`. Clone with `core.symlinks=true` (the
default on macOS and Linux) so Claude Code can load the shared skills.

## Status

Project skeleton only: the health operation in local and API mode, over the CLI, REST and
MCP. Milestones M1 to M5 in
the spec describe what comes next.
