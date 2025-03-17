#!/usr/bin/env python3
"""
Command-line tool for running tests.
"""

import argparse
import json
import logging
import sys
import subprocess
import os
import re
from pathlib import Path

# Add parent directory to path to allow importing from repo2run
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from repo2run.utils.logger import setup_logger


def find_best_working_dir(repo_path):
    """
    Find the best working directory to use for running tests.
    
    Args:
        repo_path (Path): Path to the repository.
        
    Returns:
        Path: The best working directory to use.
    """
    # Check if there's a subdirectory that looks like the main project
    # Common patterns for main project directories
    common_names = [
        "src", "app", "lib", 
        # Look for directories with the same name as the parent directory
        repo_path.name, 
        # Look for directories with "-master" suffix (common in GitHub downloads)
        f"{repo_path.name}-master"
    ]
    
    # First, check if there's a tests directory in the repo_path
    if (repo_path / "tests").is_dir() or (repo_path / "test").is_dir():
        return repo_path
    
    # Check for common project directory names
    for name in common_names:
        potential_dir = repo_path / name
        if potential_dir.is_dir():
            # Check if this directory has tests
            if (potential_dir / "tests").is_dir() or (potential_dir / "test").is_dir():
                return potential_dir
            # Check if this directory has Python files
            if list(potential_dir.glob("*.py")):
                return potential_dir
    
    # If we couldn't find a better directory, use the repo_path
    return repo_path


def ensure_pytest_config(repo_path, working_dir, logger):
    """
    Ensure that a pyproject.toml file exists with proper pytest configuration.
    
    Args:
        repo_path (Path): Path to the repository.
        working_dir (Path): Path to the working directory for tests.
        logger (logging.Logger): Logger instance.
    """
    pyproject_path = working_dir / "pyproject.toml"
    
    # Check if pyproject.toml exists
    if pyproject_path.exists():
        logger.info(f"Found existing pyproject.toml at {pyproject_path}")
        
        # Read the existing file
        with open(pyproject_path, 'r') as f:
            content = f.read()
        
        # Check if pytest configuration already exists
        if "[tool.pytest.ini_options]" in content:
            logger.info("Pytest configuration already exists in pyproject.toml")
            return
        
        # Add pytest configuration to the existing file
        logger.info("Adding pytest configuration to existing pyproject.toml")
        with open(pyproject_path, 'a') as f:
            f.write("\n\n[tool.pytest.ini_options]\npythonpath = [\".\"]\n")
    else:
        # Create a new pyproject.toml file with pytest configuration
        logger.info(f"Creating pyproject.toml with pytest configuration at {pyproject_path}")
        with open(pyproject_path, 'w') as f:
            f.write("[tool.pytest.ini_options]\npythonpath = [\".\"]\n")
    
    logger.info("Updated pyproject.toml with pytest configuration")


def run_tests_with_uv(repo_path, logger):
    """
    Run tests using uv run pytest.
    
    Args:
        repo_path (Path): Path to the repository.
        logger (logging.Logger): Logger instance.
        
    Returns:
        dict: Dictionary with test results.
    """
    logger.info("Running tests")
    
    # Check if pytest is installed
    try:
        result = subprocess.run(
            ['uv', 'list', 'pytest'],
            cwd=repo_path,
            check=False,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0 or 'pytest' not in result.stdout:
            logger.info("pytest is not installed. Installing pytest...")
            
            # Install pytest as a dev dependency
            # pytest_spec = "pytest>=7.4.0" if sys.version_info.major == 3 and sys.version_info.minor >= 12 else "pytest"
            install_result = subprocess.run(
                ['uv', 'add', 'pytest', '--dev', '--frozen', '--resolution', 'lowest-direct'],
                cwd=repo_path,
                check=False,
                capture_output=True,
                text=True
            )
            
            if install_result.returncode != 0:
                logger.error(f"Failed to install pytest: {install_result.stderr}")
                return {
                    "status": "error",
                    "message": "Failed to install pytest",
                    "tests_found": 0,
                    "tests_passed": 0,
                    "tests_failed": 0,
                    "tests_skipped": 0,
                    "test_results": []
                }
    except Exception as e:
        logger.error(f"Failed to check if pytest is installed: {str(e)}")
        return {
            "status": "error",
            "message": f"Failed to check if pytest is installed: {str(e)}",
            "tests_found": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "tests_skipped": 0,
            "test_results": []
        }
    
    # Find the best working directory
    working_dir = find_best_working_dir(repo_path)
    logger.info(f"Using working directory for pytest: {working_dir}")
    
    # Ensure pytest configuration exists
    ensure_pytest_config(repo_path, working_dir, logger)
    
    # Create a modified environment with PYTHONPATH set to include the working directory
    env = dict(os.environ)
    if 'PYTHONPATH' in env:
        env['PYTHONPATH'] = f"{working_dir}:{env['PYTHONPATH']}"
    else:
        env['PYTHONPATH'] = str(working_dir)
    
    logger.info(f"Setting PYTHONPATH to: {env['PYTHONPATH']}")
    
    # Collect test cases
    logger.info("Collecting test cases")
    try:
        collect_result = subprocess.run(
            ['uv', 'run', 'pytest', '-q', '--disable-warnings'],
            cwd=working_dir,
            check=False,
            capture_output=True,
            text=True,
            env=env
        )
        
        test_case_pattern = re.compile(r'^([\w/]+\.py::[\w_]+)$', re.MULTILINE)
        test_cases = test_case_pattern.findall(collect_result.stdout)
        
        if test_cases:
            logger.info(f"Collected {len(test_cases)} test cases")
            
            # Run tests
            logger.info("Running tests")
            result = subprocess.run(
                ['uv', 'run', 'pytest', '-v'],
                cwd=working_dir,
                check=False,
                capture_output=True,
                text=True,
                env=env
            )
            
            # Parse test results
            test_results = []
            passed = 0
            failed = 0
            skipped = 0
            
            for line in result.stdout.splitlines():
                if ' PASSED ' in line:
                    test_name = line.split(' PASSED ')[0].strip()
                    test_results.append({
                        "name": test_name,
                        "status": "passed"
                    })
                    passed += 1
                elif ' FAILED ' in line:
                    test_name = line.split(' FAILED ')[0].strip()
                    test_results.append({
                        "name": test_name,
                        "status": "failed"
                    })
                    failed += 1
                elif ' SKIPPED ' in line:
                    test_name = line.split(' SKIPPED ')[0].strip()
                    test_results.append({
                        "name": test_name,
                        "status": "skipped"
                    })
                    skipped += 1
            
            status = "success" if failed == 0 else "failure"
            message = f"{passed} passed, {failed} failed, {skipped} skipped"
            
            logger.info(f"Test results: {message}")
            
            return {
                "status": status,
                "message": message,
                "tests_found": len(test_cases),
                "tests_passed": passed,
                "tests_failed": failed,
                "tests_skipped": skipped,
                "test_results": test_results,
                "stdout": result.stdout,
                "stderr": result.stderr
            }
        else:
            logger.info("No test cases found")
            return {
                "status": "success",
                "message": "No test cases found",
                "tests_found": 0,
                "tests_passed": 0,
                "tests_failed": 0,
                "tests_skipped": 0,
                "test_results": []
            }
    except Exception as e:
        logger.error(f"Failed to run tests: {str(e)}")
        return {
            "status": "error",
            "message": str(e),
            "tests_found": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "tests_skipped": 0,
            "test_results": []
        }


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description='Run tests in a repository.')
    parser.add_argument('--repo-path', type=str, default='.', help='Path to the repository.')
    parser.add_argument('--output', type=str, help='Path to save test results as JSON.')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging.')
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logger(verbose=args.verbose)
    
    # Get repository path
    repo_path = Path(args.repo_path).resolve()
    
    logger.info(f"Running tests in repository: {repo_path}")
    
    # Run tests
    results = run_tests_with_uv(repo_path, logger)
    
    # Print summary
    print(f"\nTest Results: {results['message']}")
    print(f"Tests Found: {results['tests_found']}")
    print(f"Tests Passed: {results['tests_passed']}")
    print(f"Tests Failed: {results['tests_failed']}")
    print(f"Tests Skipped: {results['tests_skipped']}")
    print(f"Status: {results['status']}")
    
    # Save results if output path is provided
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"Test results saved to {output_path}")
    
    return 0 if results['status'] == 'success' else 1


if __name__ == '__main__':
    sys.exit(main()) 