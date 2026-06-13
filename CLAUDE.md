# Decker — CLAUDE.md

## Project overview

**Decker** is a Linux application for Elgato Stream Deck hardware. The architecture has three components in the same repo:

- **Server monitor** (`src/decker/server/monitor.py`) — the process launched by `poe server`. Starts the server subprocess, then polls it continuously for health (RPyC heartbeat) and memory usage. If the server fails to respond or exceeds the memory limit (1 GiB), the monitor kills it and restarts it automatically.
- **Server** (`src/decker/server/`) — handles hardware communication via `python-elgato-streamdeck`. Runs as a separate subprocess (RPyC on port 18861) and supports multiple simultaneous clients (local and networked). Started and supervised exclusively by the server monitor.
- **Client / UI** (`src/decker/client/`) — a GUI application that connects to a single server instance. Each client communicates with the server over RPyC.

Early alpha; the hardware integration layer and server/client separation are the current focus.

## Server fault-tolerance model

`poe server` launches the **server monitor**, not the server directly. The monitor:

1. Spawns the server as a child process.
2. Periodically sends an RPyC heartbeat; a non-response counts as a failed check.
3. Periodically samples the server process's RSS memory via `/proc/<pid>/status` or `psutil`.
4. If consecutive failed heartbeats reach the threshold **or** RSS exceeds **1 GiB**, the monitor kills the child and restarts it.
5. Restart backoff and max-restart limits are configurable.

The server itself has no self-healing logic — fault tolerance is entirely the monitor's responsibility.

## Running the project

```bash
# Run the server (normal mode)
poe server

# Run the server in daemon mode
poe server --daemon --verbose

# Run the client
poe client

# Run the client with a specific command
poe client status
```

System dependency required: `libhidapi` (`sudo pacman -S hidapi` on Arch/Manjaro).

## Quality gates — run all before marking work done

```bash
poe format   # isort + black (auto-fixes; run first)
poe mypy     # type checking
poe pylint   # linting (must score ≥ 9.0)
poe test     # pytest with coverage (target ≥ 85%)
```

Run `format` before the others; it changes files that the linter then re-checks.

## Code style

- **Formatter**: black (line length 120) + isort (`black` profile). Let the formatter decide; don't fight it.
- **Types**: Always annotate — return types, parameters, and instance attributes — even when mypy doesn't require it.
- **Naming**: `snake_case` for functions/methods/variables/modules, `PascalCase` for classes, `UPPER_CASE` for module-level constants.
- **Docstrings**: Public classes and public functions only. One short line is enough unless the contract is non-obvious. No multi-paragraph docstrings. Private/internal members (`_` prefix) get no docstrings.
- **Comments**: Only when the *why* is non-obvious. Never narrate what the code already says.
- **Method size**: Keep methods under 50 lines. If a method is growing, extract a private helper rather than commenting sections.
- **Max args**: 5 per function/method (pylint enforces this).

## Testing

- Framework: `pytest` with `assertpy` for assertions.
- Target: **≥ 85% coverage** (`poetry run poe test` reports this).
- Test files live in `tests/` mirroring the source layout.
- Pylint docstring requirements are relaxed in tests (configured in `pyproject.toml`).
- Do not mock the database or other infrastructure unless absolutely necessary — prefer integration-style tests against real components.

## Architecture constraints

- `poe server` launches the monitor, which launches the server — never start the server directly in production.
- Server and client are separate entry points; keep their modules decoupled.
- Server must support multiple simultaneous clients.
- All hardware interaction goes through the server; the client never talks to hardware directly.
- Fault-tolerance (restart, health checking, memory limiting) lives in the monitor, not in the server.
- Configuration is TOML-based (`toml` library); use `flatten-dict` for nested config operations.
- RPyC is the IPC layer between server and client.

## Custom type stubs

Hand-written stubs live in `.stubs/` for libraries that lack upstream type information:
- `StreamDeck` — hardware SDK
- `rpyc` — IPC library
- `flatten_dict` — config utility

Update stubs when upstream API surfaces change: `poe stubs`.

## Decision-making

- When a design decision is ambiguous, ask rather than guess.
- Keep PRs/commits focused — split unrelated changes into separate PRs.
- Prefer explicit over implicit; favour readability over cleverness.
