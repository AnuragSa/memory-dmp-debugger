# uv Quick Reference

This project uses **uv** - a fast Python package manager written in Rust.

## Why uv?

- ⚡ **10-100x faster** than pip/poetry
- 🎯 **Simple**: No complex configuration
- 🔒 **Reliable**: Lockfile for reproducible installs
- 🐍 **Python version management**: Built-in Python installation

## Installation

```powershell
# Install uv
pip install uv

# Or use the installer (recommended)
irm https://astral.sh/uv/install.ps1 | iex
```

## Common Commands

### Project Setup

```powershell
# Install dependencies from pyproject.toml
uv sync

# Install with dev dependencies
uv sync --all-extras

# Update dependencies
uv sync --upgrade
```

### Running Commands

```powershell
# Run the CLI
uv run dump-debugger analyze "C:\Users\AnuragSaxena\Downloads\mem-dumps\dmp2.dmp" --issue "Investigate what issues do you see?" --show-commands

# Run Python scripts
uv run python script.py

# Run tests
uv run pytest

# Run formatters
uv run black src/
uv run ruff check src/
```

### Managing Dependencies

```powershell
# Add a new dependency
uv add langchain-anthropic

# Add a dev dependency
uv add --dev pytest

# Remove a dependency
uv remove package-name

# Show installed packages
uv pip list
```

### Virtual Environment

```powershell
# uv automatically manages virtual environments
# .venv is created automatically on first sync

# Activate manually (if needed)
.venv\Scripts\activate

# Deactivate
deactivate
```

## Key Differences from Poetry

| Task | Poetry | uv |
|------|--------|-----|
| Install deps | `poetry install` | `uv sync` |
| Run command | `poetry run cmd` | `uv run cmd` |
| Add dependency | `poetry add pkg` | `uv add pkg` |
| Update deps | `poetry update` | `uv sync --upgrade` |
| Show deps | `poetry show` | `uv pip list` |

## Project Files

- **pyproject.toml**: Project metadata and dependencies
- **uv.lock**: Lockfile (auto-generated, commit to git)
- **.venv/**: Virtual environment (auto-created, don't commit)

## Troubleshooting

### "uv: command not found"
```powershell
# Make sure uv is installed
pip install uv

# Or reinstall
irm https://astral.sh/uv/install.ps1 | iex
```

### Clear cache
```powershell
uv cache clean
```

### Force reinstall
```powershell
Remove-Item -Recurse -Force .venv
uv sync
```

## Learn More

- Documentation: https://docs.astral.sh/uv/
- GitHub: https://github.com/astral-sh/uv
