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

#### Comprehensive Usage Options

```bash
# Basic repository processing
repo2run --repo username/repo commit-sha [OPTIONS]
repo2run --local /path/to/local/repo [OPTIONS]

# Batch processing
repo2run --repo-list repos.txt [OPTIONS]
repo2run --local-list dirs.txt [OPTIONS]
```

#### Argument Reference

| Argument | Description | Default | Example |
|----------|-------------|---------|---------|
| `--repo FULL_NAME SHA` | Process a specific GitHub repository | None | `--repo octocat/Hello-World abc123` |
| `--local PATH` | Process a local repository | None | `--local /home/user/projects/myrepo` |
| `--repo-list FILE` | Process multiple repositories from a list file | None | `--repo-list repos.txt` |
| `--local-list FILE` | Process multiple local repositories from a list file | None | `--local-list local_repos.txt` |
| `--output-dir DIR` | Directory to store output files | `output` | `--output-dir ./results` |
| `--workspace-dir DIR` | Directory to use as workspace | Temporary directory | `--workspace-dir ./workspace` |
| `--timeout SECONDS` | Maximum execution time | 7200 (2 hours) | `--timeout 3600` |
| `--verbose` | Enable detailed logging | Disabled | `--verbose` |
| `--overwrite` | Overwrite existing output directory | Disabled | `--overwrite` |
| `--use-uv` | Use UV for dependency management | Disabled (uses pip/venv) | `--use-uv` |
| `--num-workers N` | Number of parallel processing workers | Number of CPU cores | `--num-workers 4` |
| `--collect-only` | Only collect test cases without running | Disabled | `--collect-only` |

#### Detailed Usage Examples

```bash
# 1. Process a GitHub repository with verbose logging
repo2run --repo username/repo commit-sha --output-dir ./output --verbose

# 2. Process a local repository using UV for dependency management
repo2run --local /path/to/local/repo --output-dir ./output --use-uv

# 3. Process multiple repositories in parallel
repo2run --repo-list repos.txt --output-dir ./output --num-workers 4

# 4. Process local repositories with a custom workspace
repo2run --local-list local_repos.txt --workspace-dir ./custom_workspace --output-dir ./output

# 5. Collect test cases without running tests or installing dependencies
repo2run --repo username/repo commit-sha --output-dir ./output --collect-only

# 6. Set a custom timeout and overwrite existing output
repo2run --local /path/to/local/repo --output-dir ./output --timeout 1800 --overwrite
```

#### Repository List File Format

For `--repo-list` and `--local-list`, use the following format:

```
# repos.txt or local_repos.txt
# Format: repository_identifier commit_sha
octocat/Hello-World abc123
another/repo def456
# Lines starting with # are comments
```

### Advanced Use Cases

#### Continuous Integration

```bash
# In a CI pipeline, you might want to use verbose logging and collect test cases
repo2run --repo username/repo $CI_COMMIT_SHA --output-dir ./ci_results --verbose --collect-only
```

#### Performance Testing

```bash
# Process multiple repositories with UV and parallel workers
repo2run --repo-list performance_repos.txt --use-uv --num-workers 8 --output-dir ./perf_results
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