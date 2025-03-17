# UV - Fast Python Package and Environment Management

This directory contains tools for using [UV](https://astral.sh/uv), an extremely fast Python package installer and environment manager written in Rust. UV can replace pip with 10-100x better performance.

## What is UV?

UV is a comprehensive Python project and package manager that's:
- **Fast**: 10-100x faster than pip for package installation
- **Reliable**: Deterministic builds with lockfiles
- **Easy to use**: Drop-in replacement for pip and virtual environments

## Simple Installation and Usage

The simplest way to get started with UV is:

```bash
# Install UV using pip
pip install uv

# Create a virtual environment
uv venv

# Install packages into the environment
uv pip install package_name
```

## Tools in this Directory

### 1. pip_download.py

This script has been updated to use UV for package installation. It will automatically install UV using pip if not present.

Usage:
```bash
python pip_download.py -p package_name -v version_constraints
```

Example:
```bash
python pip_download.py -p numpy -v ">=1.20.0,<2.0.0"
```

### 2. uv_environment.py

This script provides a comprehensive interface for managing Python environments using UV.

Usage:
```bash
# Create a new environment
python uv_environment.py create [--path ENV_PATH] [--python PYTHON_VERSION]

# Install dependencies
python uv_environment.py install --packages pkg1 pkg2 [--env ENV_PATH]
# OR
python uv_environment.py install --requirements requirements.txt [--env ENV_PATH]

# Run a command in an environment
python uv_environment.py run python script.py [--env ENV_PATH]

# Export requirements
python uv_environment.py export [--env ENV_PATH] [--output requirements.txt]
```

### 3. uv_simple_example.py

This script demonstrates the straightforward approach to using UV:

```bash
python uv_simple_example.py
```

It will:
1. Install UV using pip
2. Create a virtual environment with `uv venv`
3. Install packages with `uv pip install`
4. Run a test script in the environment

## Using UV with download.py

The `download.py` utility has been updated to support UV for faster package installation. You can now:

1. Use UV automatically for all pip installations (when available)
2. Explicitly specify UV as the installation tool

Example:
```python
# Using UV explicitly
waiting_list.add('requests', None, 'uv')

# Using pip (will use UV if available)
waiting_list.add('numpy', '>=1.20.0', 'pip')
```

The system will:
- Automatically install UV if not present
- Create a virtual environment at `.venv` for package installations
- Fall back to standard pip if UV is not available

## UV vs pip: Key Benefits

1. **Speed**: UV is 10-100x faster than pip for package installation
2. **Reliability**: Better dependency resolution and lockfile support
3. **Convenience**: Integrated environment management
4. **Compatibility**: Drop-in replacement for pip commands

## Common UV Commands

Here are some common UV commands that you can use directly:

```bash
# Install packages (pip replacement)
uv pip install package_name

# Install from requirements.txt
uv pip install -r requirements.txt

# Create a virtual environment
uv venv [ENV_PATH]

# Run a command in a virtual environment
uv run python script.py

# Compile requirements.txt from pyproject.toml
uv pip compile pyproject.toml -o requirements.txt
```

## Using UV in Projects

UV works well with both traditional `requirements.txt` files and modern `pyproject.toml` based workflows:

### With requirements.txt

```bash
# Create a virtual environment
uv venv

# Install dependencies
uv pip install -r requirements.txt
```

### With pyproject.toml

```bash
# Initialize a new project
uv init

# Add dependencies to pyproject.toml
uv add flask requests

# Sync dependencies
uv sync
```

## Additional Resources

- [UV Documentation](https://docs.astral.sh/uv/)
- [UV GitHub Repository](https://github.com/astral-sh/uv) 