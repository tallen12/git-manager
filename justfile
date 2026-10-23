# List available tasks.
default:
    @just --list

# Install locked dependencies.
setup:
    uv sync --locked

# Format Python code.
format:
    uv run ruff format .

# Check formatting and lint rules.
lint:
    uv run ruff format --check .
    uv run ruff check .

# Check types.
typecheck:
    uv run ty check

# Run the test suite.
test:
    uv run pytest

# Run the test suite with branch coverage (writes coverage.xml).
coverage:
    uv run pytest --cov --cov-report=term --cov-report=xml

# Run all required checks.
check: lint typecheck test

# Run the CLI (pass arguments after the recipe name).
cli *args:
    uv run git-manager {{args}}

# Start the REST server.
web:
    uv run git-manager web

# Start the MCP stdio server.
mcp:
    uv run git-manager mcp stdio

# Print a random 256-bit API token.
generate-token:
    @uv run python -c "import secrets; print(secrets.token_hex(32))"

# Build the runtime image.
docker-build:
    docker build -t git-manager .
