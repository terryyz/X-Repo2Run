"""
Test runner for Repo2Run.

This module handles finding and running tests in a repository.
"""

import logging
import os
import re
import subprocess
from pathlib import Path
import sys
from contextlib import contextmanager


@contextmanager
def change_dir(path):
    """
    Context manager to temporarily change the working directory.
    
    Args:
        path (str or Path): Path to change to.
    """
    old_dir = os.getcwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(old_dir)


class TestRunner:
    """
    Finds and runs tests in a repository.
    """
    
    def __init__(self, repo_path, venv_path=None, logger=None):
        """
        Initialize the test runner.
        
        Args:
            repo_path (Path): Path to the repository.
            venv_path (Path, optional): Path to the virtual environment. If None, a default path is used.
            logger (logging.Logger, optional): Logger instance. If None, a new logger is created.
        """
        self.repo_path = Path(repo_path)
        
        if venv_path is None:
            self.venv_path = self.repo_path / '.venv'
        else:
            self.venv_path = Path(venv_path)
        
        self.logger = logger or logging.getLogger(__name__)
    
    def find_tests(self):
        """
        Find test files in the repository.
        
        Returns:
            list: List of test file paths.
        """
        self.logger.info("Finding test files")
        
        test_files = []
        
        # Search recursively for test files
        test_patterns = [
            "**/tests/**/*test*.py",
            "**/test/**/*test*.py",
            "**/tests/**/*_test.py",
            "**/test/**/*_test.py",
            "**/test_*.py",
            "**/*_test.py"
        ]
        
        for pattern in test_patterns:
            found_files = list(self.repo_path.glob(pattern))
            self.logger.info(f"Pattern {pattern} found {len(found_files)} files")
            test_files.extend(found_files)
        
        # Remove duplicates and sort
        test_files = sorted(set(test_files))
        
        self.logger.info(f"Found {len(test_files)} test files")
        for test_file in test_files:
            self.logger.info(f"Found test file: {test_file}")
        
        return test_files
    
    def check_pytest(self):
        """
        Check if pytest is installed in the virtual environment.
        
        Returns:
            bool: True if pytest is installed, False otherwise.
        """
        self.logger.info("Checking if pytest is installed")
        
        # Find the best working directory
        working_dir = self._find_best_working_dir()
        
        try:
            # Check if pytest is installed using uv list
            result = subprocess.run(
                ['uv', 'list', 'pytest'],
                cwd=working_dir,
                check=False,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0 and 'pytest' in result.stdout:
                self.logger.info(f"pytest is installed: {result.stdout.strip()}")
                return True
            else:
                self.logger.warning(f"pytest is not installed")
                return False
        except Exception as e:
            self.logger.warning(f"Failed to check if pytest is installed: {str(e)}")
            return False
    
    def install_pytest(self):
        """
        Install pytest in the virtual environment using uv.
        
        Returns:
            bool: True if pytest was successfully installed, False otherwise.
        """
        self.logger.info("Installing pytest using uv")
        
        # Find the best working directory
        working_dir = self._find_best_working_dir()
        
        try:
            self.logger.info(f"Installing pytest for Python")
            
            # Use uv add to install pytest as a dev dependency
            result = subprocess.run(
                ['uv', 'add', 'pytest', '--dev', '--frozen', '--resolution', 'lowest-direct'],
                cwd=working_dir,
                check=False,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                self.logger.info("pytest installed successfully using uv")
                return True
            else:
                self.logger.error(f"Failed to install pytest using uv: {result.stderr}")
                return False
        except Exception as e:
            self.logger.error(f"Failed to install pytest using uv: {str(e)}")
            return False
    
    def collect_tests(self):
        """
        Collect test cases using pytest.
        
        Returns:
            list: List of test case identifiers.
        """
        self.logger.info("Collecting test cases")
        
        # Find the actual working directory to use
        working_dir = self._find_best_working_dir()
        self.logger.info(f"Using working directory for pytest: {working_dir}")
        
        # Get all test files
        test_files = self.find_tests()
        
        if test_files:
            self.logger.info(f"Found {len(test_files)} potential test files in {working_dir}:")
            for test_file in test_files:
                self.logger.info(f"  Test file: {test_file.relative_to(working_dir)}")
                
                # Check if the file is importable
                try:
                    with open(test_file, 'r') as f:
                        first_few_lines = ''.join(f.readline() for _ in range(10))
                    self.logger.debug(f"First few lines of {test_file.name}:\n{first_few_lines}")
                except Exception as e:
                    self.logger.warning(f"Could not read {test_file}: {str(e)}")
        else:
            self.logger.warning(f"No test files found in {working_dir}")
                
        try:
            # Create a modified environment with PYTHONPATH set to include the working directory
            env = dict(os.environ)
            if 'PYTHONPATH' in env:
                env['PYTHONPATH'] = f"{working_dir}:{env['PYTHONPATH']}"
            else:
                env['PYTHONPATH'] = str(working_dir)
            
            self.logger.info(f"Setting PYTHONPATH to: {env['PYTHONPATH']}")
            
            # Run pytest with verbose output to collect tests
            result = self._run_in_venv(
                ['pytest', '--collect-only', '-v'],
                cwd=working_dir,
                env=env
            )
            
            self.logger.info(f"Test collection output:\n{result.stdout}")
            if result.stderr:
                self.logger.warning(f"Test collection stderr:\n{result.stderr}")
                
                # Check if this is a dependency issue
                if "Failed to build" in result.stderr or "ImportError" in result.stderr:
                    self.logger.warning("Dependency issues detected during test collection")
            
            # Extract test cases using regex
            test_case_pattern = re.compile(r'^([\w/]+\.py::[\w_]+)$', re.MULTILINE)
            test_cases = test_case_pattern.findall(result.stdout)
            
            self.logger.info(f"Collected {len(test_cases)} test cases")
            return test_cases
            
        except Exception as e:
            self.logger.warning(f"Failed to collect test cases: {str(e)}")
            return []
    
    def _find_best_working_dir(self):
        """
        Find the best working directory to use for running tests.
        
        Returns:
            Path: The best working directory to use.
        """
        # Check if there's a subdirectory that looks like the main project
        # Common patterns for main project directories
        common_names = [
            "src", "app", "lib", 
            # Look for directories with the same name as the parent directory
            self.repo_path.name, 
            # Look for directories with "-master" suffix (common in GitHub downloads)
            f"{self.repo_path.name}-master"
        ]
        
        # First, check if there's a tests directory in the repo_path
        if (self.repo_path / "tests").is_dir() or (self.repo_path / "test").is_dir():
            self.logger.info(f"Found tests directory in repository root")
            return self.repo_path
        
        # Check for common project directory names
        for name in common_names:
            potential_dir = self.repo_path / name
            if potential_dir.is_dir():
                # Check if this directory has tests
                if (potential_dir / "tests").is_dir() or (potential_dir / "test").is_dir():
                    self.logger.info(f"Found tests directory in {name}/")
                    return potential_dir
                # Check if this directory has Python files
                if list(potential_dir.glob("*.py")):
                    self.logger.info(f"Found Python files in {name}/")
                    return potential_dir
        
        # If we couldn't find a better directory, use the repo_path
        return self.repo_path
    
    def _run_in_venv(self, command, cwd=None, env=None):
        """
        Run a command in the virtual environment using uv run.
        
        Args:
            command (list): Command to run as a list of strings.
            cwd (Path, optional): Working directory. Defaults to None.
            env (dict, optional): Environment variables. Defaults to None.
            
        Returns:
            subprocess.CompletedProcess: Result of the command.
        """
        # Use uv run for all commands
        uv_command = ['uv', 'run']
        uv_command.extend(command)
                
        # Ensure we're using the provided working directory or the repository path
        # Convert to absolute path to avoid any relative path issues
        working_dir = cwd or self.repo_path
        working_dir = Path(working_dir).absolute()
        
        self.logger.info(f"Running command with uv: {' '.join(uv_command)}")
        self.logger.info(f"Using working directory: {working_dir}")
        
        # Use the context manager to temporarily change the working directory
        with change_dir(working_dir):
            # Log the actual current working directory to verify
            self.logger.info(f"Current working directory: {os.getcwd()}")
            
            return subprocess.run(
                uv_command,
                # No need to specify cwd here as we've already changed directory
                check=False,
                capture_output=True,
                text=True,
                env=env
            )
    
    def run_tests(self):
        """Run tests using pytest."""
        self.logger.info("Running tests")
        
        # Check if pytest is installed
        if not self.check_pytest():
            self.logger.info("pytest is not installed. Attempting to install it.")
            if not self.install_pytest():
                self.logger.error("Failed to install pytest. Cannot run tests.")
                return {
                    "status": "error",
                    "message": "Failed to install pytest",
                    "tests_found": 0,
                    "tests_passed": 0,
                    "tests_failed": 0,
                    "tests_skipped": 0,
                    "test_results": []
                }
        
        # Find the best working directory
        working_dir = self._find_best_working_dir()
        
        # Create a modified environment with PYTHONPATH set to include the working directory
        env = dict(os.environ)
        if 'PYTHONPATH' in env:
            env['PYTHONPATH'] = f"{working_dir}:{env['PYTHONPATH']}"
        else:
            env['PYTHONPATH'] = str(working_dir)
        
        # Add Django settings module if not already set
        if 'DJANGO_SETTINGS_MODULE' not in env:
            env['DJANGO_SETTINGS_MODULE'] = 'app.settings'
        
        self.logger.info(f"Setting PYTHONPATH to: {env['PYTHONPATH']}")
        self.logger.info(f"Using Django settings module: {env['DJANGO_SETTINGS_MODULE']}")
        
        try:
            # First collect tests to verify we can find them
            test_cases = self.collect_tests()
            
            # Check if we have test files even if no test cases were collected
            test_files = self.find_tests()
            
            if not test_cases:
                self.logger.warning("No test cases found")
                
                if test_files:
                    self.logger.warning(f"Found {len(test_files)} test files but couldn't collect test cases. This is likely due to dependency issues.")
                    # We'll still return 0 tests found here, but the main.py will handle this case
                    self.logger.info("Returning 0 tests found, but main.py will update this based on test files")
                else:
                    self.logger.warning("No test files found either")
                
                return {
                    "status": "success",
                    "message": "No test cases found",
                    "tests_found": 0,
                    "tests_passed": 0,
                    "tests_failed": 0,
                    "tests_skipped": 0,
                    "test_results": []
                }
            
            # Run pytest with verbose output
            result = self._run_in_venv(
                ['pytest', '-v', '--disable-warnings'],
                cwd=working_dir,
                env=env
            )
            
            # Parse test results
            test_results = []
            passed = 0
            failed = 0
            skipped = 0
            
            # Parse the output to count tests
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
                elif ' ERROR ' in line:
                    test_name = line.split(' ERROR ')[0].strip()
                    test_results.append({
                        "name": test_name,
                        "status": "error"
                    })
                    failed += 1
                elif ' SKIPPED ' in line:
                    test_name = line.split(' SKIPPED ')[0].strip()
                    test_results.append({
                        "name": test_name,
                        "status": "skipped"
                    })
                    skipped += 1
            
            # Calculate total tests found
            total_tests = passed + failed + skipped
            
            status = "success" if failed == 0 else "failure"
            message = f"{passed} passed, {failed} failed, {skipped} skipped"
            
            self.logger.info(f"Test results: {message}")
            
            return {
                "status": status,
                "message": message,
                "tests_found": total_tests,
                "tests_passed": passed,
                "tests_failed": failed,
                "tests_skipped": skipped,
                "test_results": test_results,
                "stdout": result.stdout,
                "stderr": result.stderr
            }
            
        except Exception as e:
            self.logger.error(f"Failed to run tests: {str(e)}")
            return {
                "status": "error",
                "message": str(e),
                "tests_found": 0,
                "tests_passed": 0,
                "tests_failed": 0,
                "tests_skipped": 0,
                "test_results": []
            } 