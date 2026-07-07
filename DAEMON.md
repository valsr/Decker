# Decker Daemon Mode

This document describes the daemon mode functionality added to the Decker server application.

## Overview

The Decker application now supports running in daemon mode with automatic health monitoring and restart capabilities. When running in daemon mode, the application:

1. Starts an RPyC server that manages the main application
2. Monitors the application health using heartbeat checks
3. Automatically restarts the application if it becomes unresponsive
4. Provides a client interface for controlling the application remotely

## Features

### Daemon Mode
- **Health Monitoring**: Sends heartbeat commands every 2 seconds (configurable)
- **Auto-restart**: Restarts the application after 2 consecutive failed heartbeats (configurable)
- **Process Management**: Manages the application lifecycle in a separate process
- **Remote Control**: Allows starting/stopping the application via RPyC

### Command Line Options

#### Daemon Mode
```bash
# Start in daemon mode with default settings
python -m decker --daemon

# Start with custom settings
python -m decker --daemon --port 18861 --heartbeat-interval 2.0 --max-failed-heartbeats 2

# Start with verbose logging
python -m decker --daemon --verbose --verbose
```

#### Normal Mode
```bash
# Start in normal mode (default)
python -m decker

# Start with verbose logging
python -m decker --verbose
```

#### Command Line Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--daemon` | flag | False | Run in daemon mode |
| `--port` | int | 18861 | Port for RPyC server |
| `--heartbeat-interval` | float | 2.0 | Time between heartbeats (seconds) |
| `--max-failed-heartbeats` | int | 2 | Max failed heartbeats before restart |
| `--verbose` / `-v` | count | 0 | Increase logging verbosity |

## Client Utilities

A client utility is provided to interact with the daemon:

```bash
# Check daemon status
python -m decker.client status

# Send heartbeat
python -m decker.client heartbeat

# Start application via daemon
python -m decker.client start

# Stop application via daemon
python -m decker.client stop

# Use custom port
python -m decker.client --port 18862 status
```

## Poetry Tasks

New poetry tasks have been added for convenience:

```bash
# Start in daemon mode
poetry run poe daemon

# Use client utilities
poetry run poe client status
poetry run poe client heartbeat
poetry run poe client start
poetry run poe client stop
```

## Architecture

### Components

1. **DaemonManager**: Main daemon controller that manages the server process and health monitoring
2. **ServerProcess**: Manages the RPyC server in a separate process
3. **DeckerService**: RPyC service that provides the API for controlling the application
4. **Application**: Enhanced with lifecycle management for daemon operation

### Health Monitoring

The daemon uses a heartbeat mechanism to monitor application health:

1. Every `heartbeat_interval` seconds, the daemon sends a heartbeat to the server
2. If a heartbeat fails, the failure counter increments
3. If `max_failed_heartbeats` consecutive failures occur, the server is restarted
4. Successful heartbeats reset the failure counter

### Process Management

- The daemon runs the RPyC server in a separate process using `multiprocessing`
- The server process can be started, stopped, and restarted independently
- Proper signal handling ensures graceful shutdown

## API Reference

### DeckerService (RPyC)

The RPyC service exposes the following methods:

#### `exposed_start_application() -> bool`
Start the Decker application.
- Returns: `True` if started successfully, `False` otherwise

#### `exposed_stop_application() -> bool`
Stop the Decker application.
- Returns: `True` if stopped successfully, `False` otherwise

#### `exposed_heartbeat() -> dict[str, Any]`
Process a heartbeat request.
- Returns: Dictionary with status information

#### `exposed_get_status() -> dict[str, Any]`
Get the current status of the service.
- Returns: Dictionary with detailed status information

### DaemonManager

#### `start_daemon() -> bool`
Start the daemon with health monitoring.
- Returns: `True` if started successfully, `False` otherwise

#### `stop_daemon() -> bool`
Stop the daemon.
- Returns: `True` if stopped successfully, `False` otherwise

#### `get_status() -> dict[str, Any]`
Get the current daemon status.
- Returns: Dictionary with daemon status information

## Configuration

Daemon settings can be configured via:

1. Command line arguments (highest priority)
2. Configuration file (future enhancement)
3. Default values

### Default Configuration

```python
PORT = 18861
HEARTBEAT_INTERVAL = 2.0  # seconds
MAX_FAILED_HEARTBEATS = 2
```

## Examples

### Basic Daemon Usage

```bash
# Terminal 1: Start daemon
python -m decker --daemon --verbose

# Terminal 2: Interact with daemon
python -m decker.client status
python -m decker.client start
python -m decker.client heartbeat
python -m decker.client stop
```

### Custom Configuration

```bash
# Start daemon with custom settings
python -m decker --daemon \
    --port 19000 \
    --heartbeat-interval 1.0 \
    --max-failed-heartbeats 3 \
    --verbose --verbose

# Use client with custom port
python -m decker.client --port 19000 status
```

## Troubleshooting

### Common Issues

1. **Port already in use**: Change the port using `--port` argument
2. **Connection refused**: Ensure daemon is running and accessible
3. **Application won't start**: Check logs for GUI/display issues

### Logging

Use verbose flags to increase logging detail:
- `-v`: INFO level logging
- `-vv`: DEBUG level logging

### Monitoring

Check daemon status regularly:
```bash
python -m decker.client status
```

This shows:
- Daemon running status
- Server running status
- Server process ID
- Failed heartbeat count
- Configuration settings

## Development

### Running Tests

```bash
# Run all tests
poetry run poe test

# Run specific server tests
python -m pytest tests/test_server.py -v
```

### Demonstration

Use the demonstration script to see the daemon in action:

```bash
# Demonstrate daemon mode
python demo.py daemon

# Demonstrate normal mode
python demo.py normal

# Demonstrate both modes
python demo.py both
```

## Future Enhancements

Planned improvements include:

1. **Configuration File Support**: Load settings from TOML configuration
2. **Metrics Collection**: Track application performance metrics
3. **Log Rotation**: Automatic log file management
4. **Service Integration**: systemd/Windows service support
5. **Health Checks**: More sophisticated health monitoring
6. **Clustering**: Multiple daemon instances with load balancing
