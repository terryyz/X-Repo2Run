# Repo2Run

A robust tool to configure and run repositories with automated dependency management.

## Features

- Clone repositories from GitHub or use local repositories
- Extract dependencies from various sources (requirements.txt, setup.py, pyproject.toml, etc.)
- Unify requirements from multiple sources
- Install dependencies using either pip/venv (default) or UV (optional)
- Find and run tests automatically
- Generate detailed reports
- Preserves original repository structure

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/repo2run.git
cd repo2run

# Install the package
pip install -e .
```

## Usage

### Command Line Interface

#### Main Command

```bash
# Using a GitHub repository (with default pip/venv)
repo2run --repo username/repo commit-sha --output-dir ./output --verbose

# Using a local repository (with default pip/venv)
repo2run --local /path/to/local/repo --output-dir ./output --verbose

# Use UV for dependency management instead of pip/venv
repo2run --local /path/to/local/repo --output-dir ./output --use-uv --verbose

# Specify a custom workspace directory
repo2run --local /path/to/local/repo --workspace-dir ./workspace --output-dir ./output
```

#### Extract Requirements

```bash
# Extract requirements from a repository
repo2run-extract --repo-path /path/to/repo --output requirements.txt --verbose

# Extract requirements in JSON format
repo2run-extract --repo-path /path/to/repo --output requirements.json --json --verbose
```

#### Install Package

```bash
# Install a package using default pip/venv
repo2run-install -p package_name -v "==1.0.0" --verbose

# Install a package using UV
repo2run-install -p package_name -v "==1.0.0" --use-uv --verbose
```

#### Run Tests

```bash
# Run tests in a repository
repo2run-test --repo-path /path/to/repo --output test_results.json --verbose
```

### Python API

```python
from repo2run.utils.repo_manager import RepoManager
from repo2run.utils.dependency_extractor import DependencyExtractor
from repo2run.utils.dependency_installer import DependencyInstaller
from repo2run.utils.test_runner import TestRunner

# Initialize repository
repo_manager = RepoManager(workspace_dir="./workspace")
repo_path = repo_manager.clone_repository("username/repo", "commit-sha")

# Extract dependencies
extractor = DependencyExtractor(repo_path)
requirements = extractor.extract_all_requirements()
unified_requirements = extractor.unify_requirements(requirements)

# Install dependencies using pip/venv (default)
installer = DependencyInstaller(repo_path, use_uv=False)
venv_path = installer.create_virtual_environment()
installation_results = installer.install_requirements(unified_requirements, venv_path)

# Run tests with pip/venv
test_runner = TestRunner(repo_path, venv_path, use_uv=False)
test_results = test_runner.run_tests()

# Or use UV for dependency management
# installer = DependencyInstaller(repo_path, use_uv=True)
# test_runner = TestRunner(repo_path, venv_path, use_uv=True)
```

## Dependency Management Systems

Repo2Run supports two dependency management systems:

1. **pip/venv (Default)**: Uses the standard Python venv module to create virtual environments and pip for package installation.
   - More compatible with a wide range of repositories
   - No additional dependencies required

2. **UV (Optional)**: A fast Python package installer and resolver.
   - Significantly faster installation
   - Better dependency resolution in complex cases
   - Can be enabled with the `--use-uv` flag

You can choose the dependency system that works best for your use case.

## Directory Structure

When processing repositories, Repo2Run creates the following directory structure:

```
workspace_dir/
├── github/
│   └── username/
│       └── repo_name/
│           ├── (repository files)
│           └── sha.txt
└── local/
    └── repo_name/
        ├── (repository files)
        └── sha.txt
```

## Output Files

For each repository processed, Repo2Run generates the following output files:

- `{repo_name}_requirements.txt`: Unified requirements extracted from the repository
- `{repo_name}_installation_results.json`: Results of installing dependencies
- `{repo_name}_test_results.json`: Results of running tests
- `{repo_name}_summary.json`: Summary of the entire process

## Supported Dependency Sources

- requirements.txt
- setup.py
- pyproject.toml (Poetry and PEP 621)
- Pipfile
- environment.yml

## License

This project is licensed under the Apache License 2.0 - see the LICENSE file for details. 