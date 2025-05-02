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
- Support for parallel processing of multiple repositories
- Unified pipeline mode for efficient batch processing
- Test extraction and execution modes
- Skip already processed repositories
- Configurable timeouts and resource management

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

#### Basic Usage

```bash
# Single repository mode
repo2run --repo username/repo commit-sha [OPTIONS]
repo2run --local /path/to/local/repo [OPTIONS]

# Batch processing mode
repo2run --repo-list repos.txt [OPTIONS]
repo2run --local-list dirs.txt [OPTIONS]

# Test extraction mode
repo2run --repo username/repo commit-sha --extract-tests [OPTIONS]
repo2run --local /path/to/local/repo --extract-tests [OPTIONS]

# Run tests from extracted tests
repo2run --output-dir output_path --run-tests [OPTIONS]

# Global unified pipeline mode
repo2run --global --repo-list repos.txt [OPTIONS]
repo2run --global --local-list dirs.txt [OPTIONS]
```

#### Argument Reference

| Argument | Description | Default | Example |
|----------|-------------|---------|---------|
| `--repo FULL_NAME SHA` | Process a specific GitHub repository | None | `--repo octocat/Hello-World abc123` |
| `--local PATH` | Process a local repository | None | `--local /home/user/projects/myrepo` |
| `--repo-list FILE` | Process multiple repositories from a list file | None | `--repo-list repos.txt` |
| `--local-list FILE` | Process multiple local repositories from a list file | None | `--local-list local_repos.txt` |
| `--global` | Use the unified global pipeline | Disabled | `--global` |
| `--output-dir DIR` | Directory to store output files | `output` | `--output-dir ./results` |
| `--workspace-dir DIR` | Directory to use as workspace | Temporary directory | `--workspace-dir ./workspace` |
| `--timeout SECONDS` | Maximum execution time | 1800 (0.5 hours) | `--timeout 3600` |
| `--verbose` | Enable detailed logging | Disabled | `--verbose` |
| `--overwrite` | Overwrite existing output directory | Disabled | `--overwrite` |
| `--use-uv` | Use UV for dependency management | Disabled (uses pip/venv) | `--use-uv` |
| `--num-workers N` | Number of parallel processing workers | Number of CPU cores | `--num-workers 4` |
| `--max-workers N` | Number of worker threads for global mode | 4 | `--max-workers 8` |
| `--repo-range START END` | Process only a range of repositories | None (all repos) | `--repo-range 0 100` |
| `--collect-only` | Only collect test cases without running | Disabled | `--collect-only` |
| `--skip-processed` | Skip already processed repositories | Disabled | `--skip-processed` |
| `--extract-tests` | Extract test files without running | Disabled | `--extract-tests` |
| `--run-tests` | Run tests from extracted test.jsonl | Disabled | `--run-tests` |

### Unified Pipeline

The Unified Pipeline is a new workflow that:

1. Analyzes dependencies across all repositories (ignoring versions) and creates a union set
2. Installs all dependencies in a single virtual environment
3. Runs tests for each repository and identifies those that pass all tests or have no tests

This approach is more efficient when processing multiple repositories with overlapping dependencies.

#### Usage

```bash
# Process repositories from a list file
repo2run --global --repo-list repos.txt --output-dir output_path [options]

# Process local directories from a list file
repo2run --global --local-list dirs.txt --output-dir output_path [options]

# Run pipeline in separate stages
repo2run --global --repo-list repos.txt --output-dir output_path --extract-dep
repo2run --global --repo-list repos.txt --output-dir output_path --config-venv
repo2run --global --repo-list repos.txt --output-dir output_path --run-test
```

#### Output Files

The Unified Pipeline generates the following output files:

1. `requirements.txt`: Union of all dependencies across repositories (without version specifiers)
2. `repo_req.json`: Mapping of repositories to their required dependencies
3. `install_status.json`: Status of dependency installation (success/failure)
4. `records.jsonl`: Detailed logs and execution status for each repository
5. `successful_repos.json`: List of repositories that pass all tests or have no tests
6. `test.jsonl`: Extracted test files and metadata (when using --extract-tests)
7. `test_results.jsonl`: Results of running tests (when using --run-tests)

### Repository List File Format

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

#### Distributed Processing

```bash
# Process repositories in batches across multiple machines
# Machine 1: Process repos 0-99
repo2run --global --repo-list repos.txt --output-dir ./batch1 --repo-range 0 100

# Machine 2: Process repos 100-199
repo2run --global --repo-list repos.txt --output-dir ./batch2 --repo-range 100 200
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

## Supported Dependency Sources

- requirements.txt
- setup.py
- pyproject.toml (Poetry and PEP 621)
- Pipfile
- environment.yml

## License

This project is licensed under the Apache License 2.0 - see the LICENSE file for details. 