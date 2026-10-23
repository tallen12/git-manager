# Project instructions

These instructions are for every coding agent working in this repository (Claude Code,
Codex, Cursor, Copilot and others) and for humans. `AGENTS.md` is the single source of
truth: tool-specific files only point here. Keep this file short, imperative and current.

## Scope

- Git Manager is specified in `design-docs/spec.md`. Follow its architecture, decisions
  table and delivery plan (M1 to M5). Design documents do not authorize implementation;
  start a milestone only when the user asks for it.
- When behavior and the spec disagree, stop and ask, or update the spec in the same change
  with the reason.
- Git Manager reads `AGENTS.md` from the repositories it manages. Keep the **Commands**
  section below accurate: it is how this repo's own checks are found.

## Commands

All commands run through `just` and use `uv`. Never call `pip`, `python -m venv` or a
global interpreter.

- Setup: `just setup`
- Format: `just format`
- Lint: `just lint`
- Type check: `just typecheck`
- Test: `just test`
- All required checks: `just check`

## Working across agents

- Put shared instructions here, never in `CLAUDE.md`, `.cursor/rules`,
  `.github/copilot-instructions.md` or similar. Those files, if present, only point to
  `AGENTS.md`. `CLAUDE.md` imports this file with `@AGENTS.md`.
- Skills live in `.agents/skills/<skill-name>/SKILL.md`. `.claude/skills` is a symlink to
  that folder so Claude Code loads the same skills. Do not create skills elsewhere.
- A skill folder holds `SKILL.md` (YAML front matter with `name` and `description`, then
  instructions) plus optional `scripts/`, `references/` and `assets/`. Skill scripts must
  follow the same Python rules as the codebase and run with `uv run`.
- Write instructions and skills in plain Markdown with relative paths. No tool-specific
  syntax, absolute paths or references to one agent's private features.
- Do not commit agent state or caches (`.claude/settings.local.json`, session files,
  scratch notes).

## Cross-platform rules

Development happens on macOS and Linux; Git Manager itself runs in a Linux container.

- Use `pathlib.Path` for all paths; never build paths with string concatenation or
  hard-code `/` separators, home directories or `/tmp`. Use `tempfile` for temporary
  files.
- Run subprocesses with argument lists, never `shell=True`. Keep process execution behind a
  protocol so it can be faked in tests.
- Do not rely on GNU-only or BSD-only command flags in code, recipes or tests. Prefer
  Python over shell for anything non-trivial.
- Text files use UTF-8 and LF line endings (`.gitattributes`, `.editorconfig`). Open files
  with an explicit `encoding="utf-8"`.
- Linux-only behavior (users, capabilities, `prlimit`, Docker sidecar) belongs behind a
  protocol in container-specific adapters, with fakes for tests that run anywhere.

## Protocols and dependency injection

- Define behavioral interfaces with `typing.Protocol`. Pydantic schemas, dataclasses, enums
  and exceptions are value types and need no protocol.
- Keep protocols separate from implementations. Prefer small, capability-focused protocols.
- Type injected dependencies as protocols. Use constructor injection for classes and
  explicit parameters for functions.
- Construct concrete implementations only at composition roots (CLI, web and MCP startup,
  test fixtures). Domain code never instantiates its own infrastructure.
- No service locators or hidden globals. Framework injection stays in adapters.
- Rely on structural typing; add `@runtime_checkable` only when a runtime check is needed.
- Prefer composition over inheritance. Test doubles implement the same protocols.

## Types and data

- Type every parameter and return value, including `__init__`, fixtures and helpers.
- `ty` is the required type checker with every rule set to error. Do not weaken it.
- Avoid `Any`, bare containers, unchecked casts and blanket ignores. Treat unknown input as
  `object` and narrow it. Any targeted suppression needs a one-line reason.
- Model alternatives as sum types (unions of named variants, discriminated when
  serialized) and related fields as product types (frozen dataclasses internally, Pydantic
  models at boundaries). Prefer explicit success, failure and awaiting-decision variants
  over optional fields and boolean flags.
- Use enums or `Literal` for finite choices; no magic strings in domain logic.
- Prefer `match` for variants and finite states, exhaustive with `typing.assert_never`.
- Validate all external data (config, API bodies, CLI JSON output, git output) with
  explicit schemas. Generate request and response schemas from the shared models.

## Code organization

- `src` layout: all application code lives under `src/git_manager/`. Tests live in
  `tests/`, design documents in `design-docs/`.
- Organize by domain or capability (for example `branches`, `stacks`, `resolution`,
  `verification`, `approvals`, `failures`), not by horizontal layer. Adapters live in
  `cli`, `web` and `mcp`. Each domain keeps its models, protocols and implementations
  together but in separate modules.
- Importing a module must have no side effects: no workers, clients, config reads, file,
  network or subprocess access at import time.
- Prefer small pure functions for policies and transformations; use classes for state,
  lifecycle or a cohesive capability.
- Favor immutable values (`@dataclass(frozen=True, slots=True)`). Use keyword-only
  parameters for options and same-typed arguments; no boolean positional arguments or
  mutable defaults.
- Represent expected outcomes with typed result variants. Use exceptions for exceptional
  failures, catch specific types, preserve causes and never swallow errors.
- Make resource ownership explicit with context managers. Never block the event loop.
- Inject clocks, ID generators, subprocess runners and external clients.
- Use absolute imports. Comments explain why, not what. Document public contracts.

## Security rules from the spec

- Never pass git, GitHub or API credentials to the Claude process or to test commands.
- Never add a code path that lets an MCP caller approve, retarget or change sensitive
  config. Those require the `approve` scope.
- Never mount the host Docker socket by default or widen Claude's tool permissions without
  a spec change.

## Tests

- Test observable behavior and protocol contracts: state transitions, failures, recovery.
- Use realistic fakes over mocks tied to implementation details. Git tests use throwaway
  repositories (see the `repository` fixture), never the network.
- The default suite needs no credentials, Docker or network access.

## Commits

- Use Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`).
  Keep commits focused; one logical change each.
- Only commit or push when the user asks.

## Completion

Before reporting work as done, run `just check` (format check, lint, type check and
tests). Report any check that could not run and why. Never claim a check passed without
running it. Documentation-only changes do not need the test suite. Do not add
dependencies or features beyond what was asked.
