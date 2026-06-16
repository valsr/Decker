# Decker — CLAUDE.md

## Project overview

**Decker** is a Linux application for Elgato Stream Deck hardware. The architecture has three components in the same repo:

- **Server monitor** (`src/decker/server/monitor.py`) — the process launched by `poe server`. Starts the server subprocess, then polls it continuously for health (RPyC heartbeat) and memory usage. If the server fails to respond or exceeds the memory limit (1 GiB), the monitor kills it and restarts it automatically.
- **Server** (`src/decker/server/`) — handles hardware communication via `python-elgato-streamdeck`. Runs **headlessly** as a separate subprocess (RPyC on port 18861), supports multiple simultaneous clients. Started and supervised exclusively by the server monitor. Exposed RPC commands: `stop`, `heartbeat`, `status`, `devices.list`, `commands`. There is no `start` RPC — the server is already running when clients connect.
- **Client / UI** (`src/decker/client/`) — a PyQt6 GUI that connects to a single server instance over RPyC. On startup it attempts to connect; if unreachable it shows a connect form and retries automatically every 5 s. While connected it polls the server heartbeat every 5 s and returns to the connect form if the server disappears.
- **CLI client** (`src/decker/cli/`) — a terminal client (`poe cli <command>`) that introspects the server's live RPC surface via `commands()` — no hardcoded command list.

Early alpha; the hardware integration layer and server/client separation are the current focus.

## Workflow Setup

notion_project_page: https://www.notion.so/valsr/Decker-37fe2db9c65e8032803de24a8234d5d5
notion_project_ref: Development
notion_project_area: decker

## Server fault-tolerance model

`poe server` launches the **server monitor**, not the server directly. The monitor:

1. Spawns the server as a child process.
2. Periodically sends an RPyC heartbeat; a non-response counts as a failed check.
3. Periodically samples the server process's RSS memory via `/proc/<pid>/status` or `psutil`.
4. If consecutive failed heartbeats reach the threshold **or** RSS exceeds **1 GiB**, the monitor kills the child and restarts it.
5. If the server exits with **code 0** (triggered by the `stop` RPC), the monitor treats it as an intentional shutdown and exits cleanly — it does **not** restart. Any non-zero exit code is treated as a crash and triggers a restart.
6. Restart backoff and max-restart limits are configurable.

The server itself has no self-healing logic — fault tolerance is entirely the monitor's responsibility.

## Running the project

```bash
# Run the server (normal mode)
poe server

# Run the server in daemon mode
poe server --daemon --verbose

# Run the GUI client
poe client

# Run the CLI client
poe cli list            # list all server commands
poe cli status          # call a specific command
poe cli stop            # gracefully stop the server (monitor exits too)
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
- The server runs headlessly; it has no GUI of its own. `application.py` exists for potential future use but is not loaded server-side.
- Do not add a `start` RPC to `DeckerService` — the server is already running when clients connect.
- `stop` RPC exits the server with code 0; the monitor interprets code 0 as intentional and stops itself. Never restart on code 0.
- Server and client are separate entry points; keep their modules decoupled.
- Server must support multiple simultaneous clients.
- All hardware interaction goes through the server; the client never talks to hardware directly.
- Fault-tolerance (restart, health checking, memory limiting) lives in the monitor, not in the server.
- Device IDs are stable 8-char CRC-32 hex strings derived from the device serial number. The selected device is persisted as `client.default_device` in the user config layer.
- Configuration is YAML-based; use `flatten-dict` for nested config operations.
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
