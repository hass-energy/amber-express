# Contribution guidelines

Contributing to this project should be as easy and transparent as possible.
We welcome contributions in many forms, whether it's:

- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features

## Github is used for everything

Github is used to host code, to track issues and feature requests, as well as accept pull requests.

Pull requests are the best way to propose changes to the codebase.

1. Fork the repo and create your branch from `main`.
2. If you've changed something, update the documentation.
3. Make sure your code lints and passes tests.
4. Issue that pull request!

## Development Setup

### Prerequisites

- Python 3.13+
- [uv](https://github.com/astral-sh/uv) package manager
- Node.js (for Prettier)

### Quick Start

```bash
# Clone your fork
git clone https://github.com/hass-energy/amber-express.git
cd amber-express

# Install Python dependencies
uv sync

# Install Node dependencies (for Prettier)
npm ci

# Run tests
uv run pytest

# Run linters
uv run ruff check
uv run ruff format --check

# Type checking
uv run pyright

# Format JSON files
npx prettier --check .
```

## Any contributions you make will be under the MIT Software License

In short, when you submit code changes, your submissions are understood to be under the same [MIT License](http://choosealicense.com/licenses/mit/) that covers the project.
Feel free to contact the maintainers if that's a concern.

## Report bugs using Github's [issues](../../issues)

GitHub issues are used to track public bugs.
Report a bug by [opening a new issue](../../issues/new/choose); it's that easy!

## Write bug reports with detail, background, and sample code

**Great Bug Reports** tend to have:

- A quick summary and/or background
- Steps to reproduce
  - Be specific!
  - Give sample code if you can.
- What you expected would happen
- What actually happens
- Notes (possibly including why you think this might be happening, or stuff you tried that didn't work)

## Use a Consistent Coding Style

### Python Code

Use [ruff](https://github.com/astral-sh/ruff) to make sure the code follows the style:

```bash
# Check code style
uv run ruff check custom_components/ tests/

# Auto-format code
uv run ruff format custom_components/ tests/
```

### JSON Files

Use [Prettier](https://prettier.io/) for JSON files:

```bash
# Check formatting
npx prettier --check .

# Auto-format
npx prettier --write .
```

## Test your code modification

Run the test suite before submitting:

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=custom_components/amber_express --cov-report=html

# Run specific test file
uv run pytest tests/test_config_flow.py
```

All tests must pass before your PR can be merged.

## Type Checking

This project uses Pyright in strict mode:

```bash
uv run pyright
```

All code must pass type checking without errors.

## License

By contributing, you agree that your contributions will be licensed under its MIT License.
