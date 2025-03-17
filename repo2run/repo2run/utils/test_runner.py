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
        
        # First, try to detect if there's a nested repository structure
        potential_repos = list(self.repo_path.glob("*/.git"))
        nested_repos = [p.parent for p in potential_repos if p.is_dir()]
        
        # If we found nested repositories, search in them as well
        search_paths = [self.repo_path] + nested_repos
        self.logger.info(f"Searching for tests in {len(search_paths)} locations: {[str(p) for p in search_paths]}")
        
        for path in search_paths:
            # Find test files in tests/ directory
            test_files.extend(path.glob("tests/**/*test*.py"))
            test_files.extend(path.glob("test/**/*test*.py"))
            
            # Find test files in the root directory
            test_files.extend(path.glob("test_*.py"))
            test_files.extend(path.glob("*_test.py"))
        
        # Remove duplicates and sort
        test_files = sorted(set(test_files))
        
        self.logger.info(f"Found {len(test_files)} test files")
        for test_file in test_files:
            self.logger.debug(f"Found test file: {test_file}")
        
        # If no test files found, print out current directory contents for debugging
        if not test_files:
            self.logger.warning("No test files found. Listing directory contents for debugging:")
            try:
                # Get current working directory - use absolute path of repo_path instead
                self.logger.info(f"Repository directory: {self.repo_path.absolute()}")
                
                # List contents of repository directory
                self.logger.info(f"Contents of repository directory ({self.repo_path}):")
                for item in self.repo_path.iterdir():
                    item_type = "DIR" if item.is_dir() else "FILE"
                    self.logger.info(f"  {item_type}: {item.name}")
                
                # If there are nested repos, list their contents too
                for repo in nested_repos:
                    self.logger.info(f"Contents of nested repository ({repo}):")
                    for item in repo.iterdir():
                        item_type = "DIR" if item.is_dir() else "FILE"
                        self.logger.info(f"  {item_type}: {item.name}")
            except Exception as e:
                self.logger.error(f"Error listing directory contents: {str(e)}")
            
        return test_files
    
    def check_pytest(self):
        """
        Check if pytest is installed in the virtual environment.
        
        Returns:
            bool: True if pytest is installed, False otherwise.
        """
        self.logger.info("Checking if pytest is installed")
        
        try:
            # Check if pytest is installed using uv list
            result = subprocess.run(
                ['uv', 'list', 'pytest'],
                cwd=self.repo_path,
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
        
        try:
            self.logger.info(f"Installing pytest for Python")
            
            # Use uv add to install pytest as a dev dependency
            result = subprocess.run(
                ['uv', 'add', 'pytest', '--dev', '--frozen', '--resolution', 'lowest-direct'],
                cwd=self.repo_path,
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
        
        # First, let's check what test files actually exist
        test_files = []
        test_files.extend(working_dir.glob("tests/**/*test*.py"))
        test_files.extend(working_dir.glob("test/**/*test*.py"))
        test_files.extend(working_dir.glob("test_*.py"))
        test_files.extend(working_dir.glob("*_test.py"))
        
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
            
            # Try with more verbose output to see what's happening
            self.logger.info("Running pytest with verbose collection")
            verbose_result = self._run_in_venv(
                ['pytest', '--collect-only', '-v'],
                cwd=working_dir,
                env=env
            )
            self.logger.info(f"Verbose collection output:\n{verbose_result.stdout}")
            if verbose_result.stderr:
                self.logger.warning(f"Verbose collection stderr:\n{verbose_result.stderr}")
            
            # Now try the regular collection
            result = self._run_in_venv(
                ['pytest', '--collect-only', '-q', '--disable-warnings'],
                cwd=working_dir,
                env=env
            )
            
            if result.returncode == 0 or result.returncode == 5:
                # Extract test cases using regex
                test_case_pattern = re.compile(r'^([\w/]+\.py::[\w_]+)$', re.MULTILINE)
                test_cases = test_case_pattern.findall(result.stdout)
                
                self.logger.info(f"Collected {len(test_cases)} test cases")
                return test_cases
            else:
                self.logger.warning(f"Failed to collect test cases: {result.stderr}")
                
                # Try running pytest directly on the test files
                if test_files:
                    self.logger.info("Trying to run pytest directly on test files")
                    for test_file in test_files:
                        direct_result = self._run_in_venv(
                            ['pytest', str(test_file.relative_to(working_dir)), '--collect-only', '-v'],
                            cwd=working_dir,
                            env=env
                        )
                        self.logger.info(f"Direct collection for {test_file.name}:\n{direct_result.stdout}")
                        if direct_result.stderr:
                            self.logger.warning(f"Direct collection stderr for {test_file.name}:\n{direct_result.stderr}")
                
                return []
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
        """
        Run tests using pytest.
        
        Returns:
            dict: Dictionary with test results.
        """
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
        
        self.logger.info(f"Setting PYTHONPATH to: {env['PYTHONPATH']}")
        
        # Find test files directly
        test_files = []
        test_files.extend(working_dir.glob("tests/**/*test*.py"))
        test_files.extend(working_dir.glob("test/**/*test*.py"))
        test_files.extend(working_dir.glob("test_*.py"))
        test_files.extend(working_dir.glob("*_test.py"))
        
        # Collect test cases
        test_cases = self.collect_tests()
        
        if not test_cases:
            self.logger.info("No test cases found through pytest collection")
            
            # If we have test files but no test cases, try running the tests directly
            if test_files:
                self.logger.info(f"Found {len(test_files)} test files. Trying to run them directly.")
                
                # Run tests directly on the files
                all_results = []
                passed = 0
                failed = 0
                skipped = 0
                
                for test_file in test_files:
                    self.logger.info(f"Running tests in {test_file.relative_to(working_dir)}")
                    try:
                        file_result = self._run_in_venv(
                            ['pytest', str(test_file.relative_to(working_dir)), '-v'],
                            cwd=working_dir,
                            env=env
                        )
                        
                        # Parse results for this file
                        file_passed = 0
                        file_failed = 0
                        file_skipped = 0
                        file_results = []
                        
                        for line in file_result.stdout.splitlines():
                            if ' PASSED ' in line:
                                test_name = line.split(' PASSED ')[0].strip()
                                file_results.append({
                                    "name": test_name,
                                    "status": "passed"
                                })
                                file_passed += 1
                            elif ' FAILED ' in line:
                                test_name = line.split(' FAILED ')[0].strip()
                                file_results.append({
                                    "name": test_name,
                                    "status": "failed"
                                })
                                file_failed += 1
                            elif ' SKIPPED ' in line:
                                test_name = line.split(' SKIPPED ')[0].strip()
                                file_results.append({
                                    "name": test_name,
                                    "status": "skipped"
                                })
                                file_skipped += 1
                        
                        passed += file_passed
                        failed += file_failed
                        skipped += file_skipped
                        all_results.extend(file_results)
                        
                        self.logger.info(f"Results for {test_file.name}: {file_passed} passed, {file_failed} failed, {file_skipped} skipped")
                    except Exception as e:
                        self.logger.error(f"Error running tests in {test_file.name}: {str(e)}")
                
                if all_results:
                    status = "success" if failed == 0 else "failure"
                    message = f"{passed} passed, {failed} failed, {skipped} skipped (direct file execution)"
                    
                    self.logger.info(f"Test results: {message}")
                    
                    return {
                        "status": status,
                        "message": message,
                        "tests_found": len(all_results),
                        "tests_passed": passed,
                        "tests_failed": failed,
                        "tests_skipped": skipped,
                        "test_results": all_results,
                        "note": "Tests were run directly on files, not through pytest collection"
                    }
            
            # Print out current directory and file listing for debugging
            try:
                # Get current working directory - use absolute path of repo_path instead
                self.logger.info(f"Repository directory: {self.repo_path.absolute()}")
                
                # List contents of repository directory
                self.logger.info(f"Contents of repository directory ({self.repo_path}):")
                for item in self.repo_path.iterdir():
                    item_type = "DIR" if item.is_dir() else "FILE"
                    self.logger.info(f"  {item_type}: {item.name}")
                
                # Try to find any Python files in the repository
                python_files = list(self.repo_path.glob("**/*.py"))
                self.logger.info(f"Found {len(python_files)} Python files in repository")
                if python_files:
                    self.logger.info("Sample Python files:")
                    for py_file in python_files[:10]:  # Show up to 10 files
                        self.logger.info(f"  {py_file}")
            except Exception as e:
                self.logger.error(f"Error listing directory contents: {str(e)}")
            
            return {
                "status": "success",
                "message": "No test cases found",
                "tests_found": 0,
                "tests_passed": 0,
                "tests_failed": 0,
                "tests_skipped": 0,
                "test_results": []
            }
        else:
            # Run tests        
            try:
                result = self._run_in_venv(
                    ['pytest', '-v'],
                    cwd=working_dir,
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
                
                self.logger.info(f"Test results: {message}")
                
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
            except Exception as e:
                self.logger.error(f"Failed to run tests: {str(e)}")
                
                return {
                    "status": "error",
                    "message": str(e),
                    "tests_found": len(test_cases),
                    "tests_passed": 0,
                    "tests_failed": 0,
                    "tests_skipped": 0,
                    "test_results": []
                } 