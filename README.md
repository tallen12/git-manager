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
just cli health
just web       # REST on http://127.0.0.1:8765, GET /healthz
just mcp       # MCP over stdio
```

The CLI is `git-manager`; once installed on `PATH`, git also runs it as `git manager`.

## Status

Project skeleton only: health endpoints on the CLI, REST and MCP. Milestones M1 to M5 in
the spec describe what comes next.
