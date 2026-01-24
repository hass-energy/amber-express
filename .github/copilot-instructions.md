---
description: Amber Express project context and agent behavioral rules
alwaysApply: true
---

# GitHub Copilot Instructions

This repository contains **Amber Express** - a Python 3.13+ Home Assistant custom component for real-time Amber Electric pricing with smart polling and WebSocket support.

## Project overview

Amber Express provides fast, real-time electricity pricing for Amber Electric customers in Australia. Key features:

- **Smart polling**: Cron-based polling inspired by amber2mqtt - polls frequently at interval start, stops once confirmed price received
- **WebSocket redundancy**: Optional connection to Amber's WebSocket API with automatic fallback to polling
- **HAEO compatibility**: Forecast sensors designed to work seamlessly with HAEO for energy optimization
- **Flexible pricing**: Choose between AEMO-based (per_kwh) or Amber's predicted pricing (advanced_price_predicted)

### Core components

- **Config Flow** (`config_flow.py`): Two-step setup (API token → site selection) with options flow
- **Coordinator** (`coordinator.py`): Smart polling with estimate detection and data merging
- **WebSocket** (`websocket.py`): Persistent WebSocket connection with exponential backoff
- **Sensors** (`sensor.py`, `binary_sensor.py`): Price, forecast, descriptor, renewables, and spike sensors

### Project structure

```
custom_components/amber_electric_live/
├── __init__.py           # Integration setup
├── config_flow.py        # Config and options flows
├── const.py              # Constants and defaults
├── coordinator.py        # Smart polling coordinator
├── websocket.py          # WebSocket client
├── sensor.py             # Sensor platform
├── binary_sensor.py      # Binary sensor platform
└── translations/         # i18n strings
    └── en.json
tests/                    # Test suite
```

## Development tools

- **Package manager**: uv (use `uv sync` for dependencies, `uv run` to execute tools)
- **Testing**: pytest with pytest-homeassistant-custom-component
- **Linting/Formatting**: Ruff (Python), Prettier (JSON)
- **Type checking**: Pyright (strict mode)

## Agent behavioral rules

### Design principles

**Convention over configuration**: Prefer uniform patterns that work the same everywhere.

- Derive behavior from existing structure rather than adding metadata flags
- Make all instances of a pattern work the same way - no special cases
- Let config flow validation enforce constraints so downstream code can assume valid data

**Composition over complexity**: Build features by composing simple, focused components.

- Separate concerns: validation happens at config flow boundaries
- Avoid "check if X then do Y else do Z" patterns

### Clean changes

When making changes, don't leave behind comments describing what was once there.
Comments should describe code as it exists.

### Error context

The main branch is always clean. Any errors or warnings you encounter are from recent changes and must be fixed.

### Code review guidelines

Rely on linting tools (Ruff and Pyright) for issues they detect. Focus review on:

- Logic errors and bugs
- Architectural concerns
- Performance issues
- Missing tests

## Code standards

- **Python**: 3.13+ with modern features (pattern matching, `str | None` syntax, dataclasses)
- **Type hints**: Required on all functions and methods
- **Formatting**: Ruff (Python), Prettier (JSON)
- **Linting**: Ruff with ALL rules enabled
- **Type checking**: Pyright strict mode
- **Language**: American English
- **Testing**: pytest with coverage

### Version matching

The version number must be consistent across:

- `pyproject.toml` (`version = "x.y.z"`)
- `custom_components/amber_electric_live/manifest.json` (`"version": "x.y.z"`)

When updating version numbers, update both files together.

## Self-maintenance

When the user provides feedback about systemic corrections, update the appropriate instruction file to capture that feedback for future sessions.
