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
    
    def __init__(self, repo_path, venv_path=None, use_uv=True, logger=None):
        """
        Initialize the test runner.
        
        Args:
            repo_path (Path): Path to the repository.
            venv_path (Path, optional): Path to the virtual environment. If None, a default path is used.
            use_uv (bool): Whether to use UV for package management. If False, use pip/venv.
            logger (logging.Logger, optional): Logger instance. If None, a new logger is created.
        """
        self.repo_path = Path(repo_path)
        self.use_uv = use_uv
        
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
            "**/*_test.py",
            "**/test/*.py",
            "**/tests/*.py"
        ]
        
        # Files to exclude (paths containing these shouldn't be included)
        exclude_patterns = ['.venv', 'site-packages', 'dist-packages']
        
        for pattern in test_patterns:
            found_files = list(self.repo_path.glob(pattern))
            
            # Filter out files from exclude patterns
            filtered_files = []
            for file_path in found_files:
                relative_path = file_path.relative_to(self.repo_path)
                should_exclude = any(excl in str(relative_path) for excl in exclude_patterns)
                
                if not should_exclude:
                    filtered_files.append(file_path)
            
            self.logger.info(f"Pattern {pattern} found {len(filtered_files)} files (after filtering)")
            test_files.extend(filtered_files)
        
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
        
        if self.use_uv:
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
                self.logger.warning(f"Failed to check if pytest is installed with UV: {str(e)}")
                return False
        else:
            # Use pip to check if pytest is installed
            try:
                # Get the path to the pip executable in the virtual environment
                if sys.platform == 'win32':
                    pip_path = self.venv_path / 'Scripts' / 'pip.exe'
                else:
                    pip_path = self.venv_path / 'bin' / 'pip'
                
                if not pip_path.exists():
                    self.logger.warning(f"pip not found in virtual environment at {pip_path}")
                    return False
                
                # Check if pytest is installed using pip list
                result = subprocess.run(
                    [str(pip_path), 'list'],
                    cwd=working_dir,
                    check=False,
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0 and 'pytest' in result.stdout:
                    self.logger.info("pytest is installed via pip")
                    return True
                else:
                    self.logger.warning(f"pytest is not installed via pip")
                    return False
            except Exception as e:
                self.logger.warning(f"Failed to check if pytest is installed via pip: {str(e)}")
                return False
    
    def install_pytest(self):
        """
        Install pytest in the virtual environment using either UV or pip.
        
        Returns:
            bool: True if pytest was successfully installed, False otherwise.
        """
        # Find the best working directory
        working_dir = self._find_best_working_dir()
        
        if self.use_uv:
            self.logger.info("Installing pytest using uv")
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
        else:
            self.logger.info("Installing pytest using pip")
            try:
                # Get the path to the pip executable in the virtual environment
                if sys.platform == 'win32':
                    pip_path = self.venv_path / 'Scripts' / 'pip.exe'
                else:
                    pip_path = self.venv_path / 'bin' / 'pip'
                
                if not pip_path.exists():
                    self.logger.error(f"pip not found in virtual environment at {pip_path}")
                    return False
                
                # Install pytest using pip
                result = subprocess.run(
                    [str(pip_path), 'install', 'pytest', '--no-cache-dir'],
                    cwd=working_dir,
                    check=False,
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    self.logger.info("pytest installed successfully using pip")
                    return True
                else:
                    self.logger.error(f"Failed to install pytest using pip: {result.stderr}")
                    return False
            except Exception as e:
                self.logger.error(f"Failed to install pytest using pip: {str(e)}")
                return False
    
    def collect_tests(self):
        """
        Collect tests using pytest.
        
        Returns:
            dict: Dictionary with test collection results.
        """
        self.logger.info("Collecting tests using pytest")
        
        # Find test files
        test_files = self.find_tests()
        if not test_files:
            self.logger.warning("No test files found during collection")
            return {
                "success": True,
                "tests": []
            }
        
        # Get Python path using helper method
        try:
            python_path = self._get_python_path()
        except Exception as e:
            self.logger.error(f"Error getting Python path: {str(e)}")
            return {
                "success": False,
                "error": f"Error getting Python path: {str(e)}",
                "tests": []
            }
        
        # Try to get pytest path
        pytest_path = self._get_pytest_path()
        
        # Choose the command based on whether pytest is installed
        if pytest_path:
            self.logger.info(f"Using pytest binary at {pytest_path}")
            cmd = [
                str(pytest_path),
                '--collect-only',
                '-v'
            ]
        else:
            self.logger.info("Using python -m pytest")
            cmd = [
                str(python_path),
                '-m',
                'pytest',
                '--collect-only',
                '-v'
            ]
        
        # Current directory to change back to
        current_dir = os.getcwd()
        
        try:
            # Change to the repository directory to run collection with relative paths
            os.chdir(self.repo_path)
            
            # Convert test files to paths relative to repo_path
            relative_test_files = []
            for test_file in test_files:
                try:
                    relative_path = test_file.relative_to(self.repo_path)
                    relative_test_files.append(str(relative_path))
                except ValueError:
                    # If we can't get a relative path, use the absolute path
                    self.logger.warning(f"Couldn't get relative path for {test_file}, using absolute path")
                    relative_test_files.append(str(test_file))
            
            # Add relative paths to command
            cmd.extend(relative_test_files)
            
            # Run pytest in collect-only mode
            self.logger.info(f"Running collection command from {self.repo_path}: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True
            )
            
            output = result.stdout
            
            # Extract test names using regex
            tests = []
            collection_pattern = re.compile(r"<(?:Function|TestCaseFunction|Module)\s+([^>]+)>")
            for match in collection_pattern.finditer(output):
                test_name = match.group(1)
                if test_name and test_name not in tests:
                    tests.append(test_name)
            
            success = result.returncode == 0
            self.logger.info(f"Collected {len(tests)} tests, success: {success}")
            
            if not success:
                self.logger.warning(f"Collection failed with return code {result.returncode}: {result.stderr}")
            
            return {
                "success": success,
                "tests": tests,
                "output": output,
                "error": result.stderr if not success else ""
            }
        except Exception as e:
            self.logger.error(f"Error collecting tests: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "tests": []
            }
        finally:
            # Change back to the original directory
            os.chdir(current_dir)
    
    def _find_best_working_dir(self):
        """
        Find the best working directory for running tests.
        This is typically the directory containing setup.py or pyproject.toml.
        
        Returns:
            Path: The best working directory.
        """
        setup_py = self.repo_path / "setup.py"
        pyproject_toml = self.repo_path / "pyproject.toml"
        
        if setup_py.exists():
            self.logger.info(f"Using directory with setup.py: {self.repo_path}")
            return self.repo_path
        elif pyproject_toml.exists():
            self.logger.info(f"Using directory with pyproject.toml: {self.repo_path}")
            return self.repo_path
        
        # Look for setup.py or pyproject.toml in subdirectories
        for item in self.repo_path.glob("**/setup.py"):
            self.logger.info(f"Using directory with setup.py: {item.parent}")
            return item.parent
        
        for item in self.repo_path.glob("**/pyproject.toml"):
            self.logger.info(f"Using directory with pyproject.toml: {item.parent}")
            return item.parent
        
        # If no setup.py or pyproject.toml, look for a tests directory
        for item in self.repo_path.glob("**/tests"):
            if item.is_dir():
                self.logger.info(f"Using parent of tests directory: {item.parent}")
                return item.parent
        
        # If nothing found, use the repository root
        self.logger.info(f"Using repository root: {self.repo_path}")
        return self.repo_path
    
    def _run_in_venv(self, command, cwd=None, env=None):
        """
        Run a command in the virtual environment.
        
        Args:
            command (list): Command to run.
            cwd (Path, optional): Working directory. If None, the repository root is used.
            env (dict, optional): Environment variables. If None, the current environment is used.
        
        Returns:
            dict: Dictionary with command result.
        """
        if cwd is None:
            cwd = self.repo_path
        
        if env is None:
            env = os.environ.copy()
        
        self.logger.info(f"Running command: {' '.join(command)}")
        
        # Get the path to the Python executable in the virtual environment
        python_path = self._get_python_path()
        
        if command[0] == "pytest":
            # If the command starts with pytest, use python -m pytest instead
            command = [str(python_path), "-m", "pytest"] + command[1:]
        else:
            # Otherwise, prepend the Python path
            command = [str(python_path)] + command
        
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                check=False,
                capture_output=True,
                text=True
            )
            
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr
            }
        except Exception as e:
            self.logger.error(f"Error running command: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "returncode": -1,
                "stdout": "",
                "stderr": str(e)
            }
    
    def _get_python_path(self):
        """
        Get the path to the Python executable in the virtual environment.
        
        Returns:
            Path: Path to the Python executable.
        """
        if sys.platform == 'win32':
            python_path = self.venv_path / 'Scripts' / 'python.exe'
        else:
            python_path = self.venv_path / 'bin' / 'python'
        
        # Always use absolute paths
        python_path = python_path.absolute()
        
        if not python_path.exists():
            self.logger.error(f"Python not found in virtual environment at {python_path}")
            raise RuntimeError(f"Python not found in virtual environment at {python_path}")
        
        return python_path
    
    def _get_pytest_path(self):
        """
        Get the path to the pytest executable in the virtual environment.
        
        Returns:
            Path: Path to the pytest executable.
        """
        if sys.platform == 'win32':
            pytest_path = self.venv_path / 'Scripts' / 'pytest.exe'
        else:
            pytest_path = self.venv_path / 'bin' / 'pytest'
        
        # Always use absolute paths
        pytest_path = pytest_path.absolute()
        
        if not pytest_path.exists():
            self.logger.warning(f"pytest not found at {pytest_path}, falling back to using python -m pytest")
            return None
        
        return pytest_path
    
    def run_tests(self):
        """
        Run tests in the repository.
        
        Returns:
            dict: Dictionary with test results.
        """
        self.logger.info(f"Running tests in {self.repo_path}")
        
        # Check if the virtual environment exists
        if not self.venv_path.exists():
            self.logger.error(f"Virtual environment not found at {self.venv_path}")
            return {
                "tests_found": 0,
                "tests_passed": 0,
                "tests_failed": 0,
                "tests_skipped": 0,
                "test_results": [],
                "status": "error",
                "error": f"Virtual environment not found at {self.venv_path}"
            }
        
        # Get Python path using helper method
        try:
            python_path = self._get_python_path()
        except Exception as e:
            self.logger.error(f"Error getting Python path: {str(e)}")
            return {
                "tests_found": 0,
                "tests_passed": 0,
                "tests_failed": 0,
                "tests_skipped": 0,
                "test_results": [],
                "status": "error",
                "error": f"Error getting Python path: {str(e)}"
            }
        
        # Find all test files
        test_files = self.find_tests()
        self.logger.info(f"Found {len(test_files)} test files")
        
        # If no test files found, return empty results
        if not test_files:
            self.logger.warning("No test files found")
            return {
                "tests_found": 0,
                "tests_passed": 0,
                "tests_failed": 0,
                "tests_skipped": 0,
                "test_results": [],
                "status": "success"
            }
        
        # Try to get pytest path, but it's okay if it doesn't exist
        pytest_path = self._get_pytest_path()
        
        # Install pytest if it's not found
        if not pytest_path:
            self.logger.info("pytest not found, attempting to install it")
            if not self.install_pytest():
                self.logger.error("Failed to install pytest, cannot run tests")
                raise RuntimeError("Failed to install pytest, cannot run tests")
            # Try again to get pytest path after installation
            pytest_path = self._get_pytest_path()
        
        # Choose the command based on whether pytest is installed
        if pytest_path:
            self.logger.info(f"Using pytest binary at {pytest_path}")
            cmd = [
                str(pytest_path),
                '-v'
            ]
        else:
            self.logger.info("Using python -m pytest")
            cmd = [
                str(python_path),
                '-m',
                'pytest',
                '-v'
            ]
        
        # Add all test files as arguments, converting them to relative paths
        # This helps avoid pathname issues when running pytest
        current_dir = os.getcwd()
        try:
            # Change to the repository directory to run tests with relative paths
            os.chdir(self.repo_path)
            
            # Convert test files to paths relative to repo_path
            relative_test_files = []
            for test_file in test_files:
                try:
                    relative_path = test_file.relative_to(self.repo_path)
                    relative_test_files.append(str(relative_path))
                except ValueError:
                    # If we can't get a relative path, use the absolute path
                    self.logger.warning(f"Couldn't get relative path for {test_file}, using absolute path")
                    relative_test_files.append(str(test_file))
            
            # Add relative paths to command
            cmd.extend(relative_test_files)
            
            # Run the tests
            self.logger.info(f"Running command from {self.repo_path}: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True
            )
            
            # Parse test results
            tests_found, tests_passed, tests_failed, tests_skipped, test_results = self._parse_test_results(result.stdout, result.stderr)
            
            self.logger.info(f"Tests found: {tests_found}, passed: {tests_passed}, failed: {tests_failed}, skipped: {tests_skipped}")
            
            return {
                "tests_found": tests_found,
                "tests_passed": tests_passed,
                "tests_failed": tests_failed,
                "tests_skipped": tests_skipped,
                "test_results": test_results,
                "status": "success"
            }
        except Exception as e:
            self.logger.error(f"Error running tests: {str(e)}")
            return {
                "tests_found": len(test_files),
                "tests_passed": 0,
                "tests_failed": len(test_files),
                "tests_skipped": 0,
                "test_results": [{"name": str(f.relative_to(self.repo_path)), "status": "error", "message": str(e)} for f in test_files],
                "status": "error",
                "error": str(e)
            }
        finally:
            # Change back to the original directory
            os.chdir(current_dir)
    
    def _parse_test_results(self, stdout, stderr):
        """
        Parse test results from stdout and stderr.
        
        Args:
            stdout (str): Standard output from the test command.
            stderr (str): Standard error output from the test command.
        
        Returns:
            tuple: Tuple containing tests_found, tests_passed, tests_failed, tests_skipped, and test_results.
        """
        # Extract test summary
        tests_found = 0
        tests_passed = 0
        tests_failed = 0
        tests_skipped = 0
        
        # Try to parse the test summary using regex
        summary_pattern = re.compile(r"=+\s*(\d+)\s+passed[,\s]+(\d+)\s+skipped[,\s]+(\d+)\s+failed")
        for line in stdout.splitlines():
            summary_match = summary_pattern.search(line)
            if summary_match:
                tests_passed = int(summary_match.group(1))
                tests_skipped = int(summary_match.group(2))
                tests_failed = int(summary_match.group(3))
                tests_found = tests_passed + tests_skipped + tests_failed
                break
        
        # Also try an alternative pattern (pytest can have different output formats)
        if tests_found == 0:
            alt_pattern = re.compile(r"=+\s+(\d+)\s+passed,?\s*(\d+)\s+skipped,?\s*(\d+)\s+failed")
            for line in stdout.splitlines():
                match = alt_pattern.search(line)
                if match:
                    tests_passed = int(match.group(1))
                    tests_skipped = int(match.group(2))
                    tests_failed = int(match.group(3))
                    tests_found = tests_passed + tests_skipped + tests_failed
                    break
        
        # If we couldn't parse the summary, try to count the tests
        if tests_found == 0:
            # Try to parse collection statistics if present
            collection_pattern = re.compile(r"collected\s+(\d+)\s+items")
            for line in stdout.splitlines():
                match = collection_pattern.search(line)
                if match:
                    tests_found = int(match.group(1))
                    break
            
            # If still no count, use test files
            if tests_found == 0:
                test_files = self.find_tests()
                tests_found = len(test_files)
                
            # Check for various failure conditions
            if stderr and ("error" in stderr.lower() or "exception" in stderr.lower()):
                # All tests failed if there was an error
                tests_failed = tests_found
            elif stdout and "no tests ran" in stdout.lower():
                # No tests ran
                tests_skipped = tests_found
            elif "FAILURES" in stdout:
                # Some tests failed
                # Count failed tests by counting the "FAILED" lines
                for line in stdout.splitlines():
                    if "FAILED" in line or "ERROR" in line:
                        tests_failed += 1
            
            # If no explicit values for passed/skipped, infer them
            if tests_passed == 0 and tests_skipped == 0 and tests_failed == 0:
                # Default assumption: all tests passed if no failures detected
                tests_passed = tests_found
            elif tests_passed == 0:
                # Calculate passed tests by subtraction
                tests_passed = tests_found - tests_failed - tests_skipped
            
        # Parse individual test results
        test_results = []
        
        # Get test files to create results for
        test_files = self.find_tests()
        
        # Try to match test failures with test files
        test_file_dict = {}
        for test_file in test_files:
            test_name = str(test_file.relative_to(self.repo_path))
            test_file_dict[test_name] = {
                "file": test_file,
                "failed": False,
                "message": ""
            }
        
        # Extract failures and match them to test files
        for line in stdout.splitlines():
            for test_name in test_file_dict:
                if test_name in line and ("FAILED" in line or "ERROR" in line):
                    test_file_dict[test_name]["failed"] = True
                    # Extract failure message (next few lines)
                    message_start = stdout.find(line) + len(line)
                    next_failure = stdout.find("FAILED", message_start)
                    if next_failure == -1:
                        next_failure = len(stdout)
                    message = stdout[message_start:next_failure].strip()
                    test_file_dict[test_name]["message"] = message
                    break
        
        # Create test results using the dictionary
        for test_name, info in test_file_dict.items():
            if info["failed"]:
                test_results.append({
                    "name": test_name,
                    "status": "failure",
                    "message": info["message"]
                })
            else:
                test_results.append({
                    "name": test_name,
                    "status": "success",
                    "message": ""
                })
        
        return tests_found, tests_passed, tests_failed, tests_skipped, test_results 