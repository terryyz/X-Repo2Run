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
import threading
from contextlib import contextmanager
import tempfile
import xml.etree.ElementTree as ET
import pytest
import json
from datetime import datetime
from io import StringIO


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
    
    def __init__(self, repo_path, venv_path=None, use_uv=True, logger=None, timeout=None, test_files=None, test_metadata=None):
        """
        Initialize the test runner.
        
        Args:
            repo_path (Path): Path to the repository.
            venv_path (Path, optional): Path to the virtual environment. If None, system Python will be used.
            use_uv (bool): Whether to use UV for package management. If False, use pip/venv.
            logger (logging.Logger, optional): Logger instance. If None, a new logger is created.
            timeout (int, optional): Timeout in seconds for test processes. If None, no timeout is applied.
            test_files (list, optional): List of test file paths. If provided, these will be used instead of finding tests.
            test_metadata (dict, optional): Dictionary mapping test file paths to metadata like tested_files.
        """
        self.repo_path = Path(repo_path)
        self.use_uv = use_uv
        self.timeout = timeout
        self.test_files = test_files
        self.test_metadata = test_metadata or {}
        
        # Set up logger first so we can use it for logging
        self.logger = logger or logging.getLogger(__name__)
        
        if venv_path == None:
            # Use system Python if venv_path is explicitly set to None
            self.venv_path = None
            self.logger.info("Using system Python (no virtual environment)")
        elif isinstance(venv_path, (str, Path)):
            # Use specified virtual environment path
            self.venv_path = Path(venv_path)
            self.logger.info(f"Using virtual environment at {self.venv_path}")
        else:
            # Default to a '.venv' directory in the repository
            self.venv_path = self.repo_path / '.venv'
            self.logger.info(f"Using default virtual environment at {self.venv_path}")
        
        # Log the timeout setting for debugging
        if self.timeout:
            self.logger.info(f"TestRunner initialized with timeout: {self.timeout} seconds")
        else:
            self.logger.info("TestRunner initialized with no timeout setting")
    
    def get_test_files(self):
        """
        Get a list of test files to run.
        
        Returns:
            list: List of test files (Path objects)
        """
        # If test files were explicitly provided during initialization, use those directly
        if self.test_files is not None and len(self.test_files) > 0:
            self.logger.info(f"Using {len(self.test_files)} explicitly provided test files")
            
            # Convert string paths to Path objects if needed
            resolved_test_files = []
            for test_file in self.test_files:
                if isinstance(test_file, str):
                    # Handle various ways the path could be specified
                    test_path = Path(test_file)
                    if not test_path.is_absolute():
                        # Try as a path relative to the repo
                        repo_relative_path = self.repo_path / test_path
                        if repo_relative_path.exists():
                            resolved_test_files.append(repo_relative_path)
                            self.logger.info(f"Found test file as repo-relative path: {repo_relative_path}")
                            continue
                        
                        # Try with glob to find the file by name
                        file_name = test_path.name
                        glob_matches = list(self.repo_path.glob(f"**/{file_name}"))
                        if glob_matches:
                            # Use the first match
                            resolved_test_files.append(glob_matches[0])
                            self.logger.info(f"Found test file by name: {glob_matches[0]}")
                            continue
                    elif test_path.exists():
                        # Use the absolute path directly
                        resolved_test_files.append(test_path)
                        self.logger.info(f"Using absolute test file path: {test_path}")
                        continue
                    
                    self.logger.warning(f"Could not resolve test file path: {test_file}")
                else:
                    # It's already a Path object
                    resolved_test_files.append(test_file)
                    self.logger.info(f"Using provided test file path: {test_file}")
            
            # Return only the valid, resolved test files
            if resolved_test_files:
                return resolved_test_files
            else:
                self.logger.warning("None of the explicitly provided test files could be resolved")
                # When specified test files are provided but none could be resolved,
                # return an empty list instead of falling back to discovery
                return []
        
        # If no test files were explicitly provided, use auto-discovery
        self.logger.info("No test files explicitly provided, using auto-discovery")
        return self.find_tests()
    
    def find_tests(self):
        """
        Find all Python test files in the repository.
        
        Returns:
            list: List of test file paths.
        """
        self.logger.info("Finding test files")
        
        test_files = []
        
        # Search recursively for test files
        test_patterns = [
            # Standard test directory patterns
            "**/tests/**/*.py",
            "**/test/**/*.py",
            
            # Common test file naming patterns
            "**/tests/**/*test*.py",
            "**/test/**/*test*.py",
            "**/tests/**/*_test.py",
            "**/test/**/*_test.py",
            "**/test_*.py",
            "**/*_test.py",
            
            # Framework-specific patterns
            "**/pytest/**/*.py",
            "**/pytests/**/*.py",
            "**/*pytest*.py",
            
            # Unit test patterns
            "**/*unittest*.py",
            "**/*_unittest.py",
            "**/unittest*.py",
            
            # Integration and functional test patterns
            "**/*integration*test*.py",
            "**/*functional*test*.py",
            
            # Include general files in test directories
            "**/test/*.py",
            "**/tests/*.py",
            
            # More specific patterns for different test frameworks
            "**/*spec.py",        # Common in some testing frameworks
            "**/*conftest*.py",   # pytest configuration files
            "**/cases/**/*.py",   # Sometimes tests are in 'cases' directories
            "**/testcases/**/*.py", 
            "**/testcase/**/*.py",
            
            # Additional patterns for different naming conventions
            "**/*check*.py",      # Some projects use "check" instead of "test"
            "**/*suite*.py"       # Test suites
        ]
        
        # Files to exclude (paths containing these shouldn't be included)
        exclude_patterns = [
            '.venv', 
            'site-packages', 
            'dist-packages', 
            'build',
            '__pycache__',
            '.egg-info',
            'node_modules'
        ]
        
        # First pass: find files based on patterns
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
        
        # Second pass: content-based detection for files that might be tests but don't match our patterns
        if len(test_files) < 10:  # Increased limit to analyze more files when few patterns match
            self.logger.info("Performing content-based test file detection")
            py_files = list(self.repo_path.glob("**/*.py"))
            
            # More comprehensive set of test indicators with weighted scores
            test_indicators = {
                # Strong indicators (high score)
                'import unittest': 3,
                'import pytest': 3,
                'from unittest': 3,
                'from pytest': 3,
                'class Test': 3,
                'class.*Test': 2,
                'class.*TestCase': 3,
                '@pytest': 3,
                'pytest.fixture': 3,
                
                # Medium indicators
                'unittest.TestCase': 2,
                'def test_': 2,
                'test_.*\(': 2,  # Function calls starting with test_
                '\stest\(': 2,
                'mock': 1,
                'patch': 1,
                'MagicMock': 2,
                
                # Assertion methods (weaker, but indicative)
                'self.assert': 1,
                'self.assertEqual': 1,
                'self.assertTrue': 1,
                'self.assertFalse': 1,
                'self.assertRaises': 1,
                'assert ': 1,
                'assertIn': 1,
                'assertNotIn': 1,
                'assertIs': 1,
                'assertIsNot': 1
            }
            
            # Keep track of files we've added to avoid duplicates
            added_files = set(test_files)
            additional_test_files = []
            
            for py_file in py_files:
                # Skip if already in test_files
                if py_file in added_files:
                    continue
                
                # Skip if in exclude patterns
                relative_path = py_file.relative_to(self.repo_path)
                str_path = str(relative_path).lower()
                if any(excl in str_path for excl in exclude_patterns):
                    continue
                
                # Skip very large files to avoid memory issues
                try:
                    if py_file.stat().st_size > 500 * 1024:  # 500KB limit
                        self.logger.debug(f"Skipping large file for content analysis: {relative_path}")
                        continue
                        
                    # Check file content for test indicators
                    with open(py_file, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read()
                    
                    # Content too short is likely not a test file
                    if len(content) < 50:
                        continue
                        
                    # Use regex to search for patterns more accurately
                    import re
                    test_score = 0
                    
                    for pattern, score in test_indicators.items():
                        if re.search(pattern, content):
                            test_score += score
                    
                    # Adjust threshold based on file location and name
                    base_threshold = 3
                    
                    # Lower threshold for files in test-like directories or with test in name
                    if 'test' in str_path or 'tests' in str_path:
                        threshold = base_threshold - 1
                    # Check if file has 'test' in name (but not in directory)
                    elif 'test' in py_file.name.lower():
                        threshold = base_threshold - 1
                    # Higher threshold for files with no test indicators in path
                    else:
                        threshold = base_threshold + 1
                    
                    # Add extra points for file name/path indicators
                    file_name = py_file.name.lower()
                    if file_name.startswith('test_'):
                        test_score += 2
                    elif file_name.endswith('_test.py'):
                        test_score += 2
                    elif 'test' in file_name:
                        test_score += 1
                    
                    # Add bonus for files that contain the word "test" 
                    # or "assert" multiple times
                    test_count = len(re.findall(r'\btest\b', content.lower()))
                    if test_count > 5:
                        test_score += 1
                    
                    assert_count = len(re.findall(r'\bassert', content.lower()))
                    if assert_count > 5:
                        test_score += 1
                    
                    # If score meets threshold, consider it a test file
                    if test_score >= threshold:
                        self.logger.info(f"Detected test file via content analysis (score: {test_score}): {relative_path}")
                        additional_test_files.append(py_file)
                        added_files.add(py_file)
                        
                except Exception as e:
                    self.logger.debug(f"Error analyzing {py_file}: {e}")
            
            # Add the additional test files found
            test_files.extend(additional_test_files)
            self.logger.info(f"Content analysis found {len(additional_test_files)} additional test files")
        
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
        
        # If no venv, check system-wide pytest
        if self.venv_path is None:
            try:
                # Check if pytest is installed using command directly
                result = subprocess.run(
                    ['pytest', '--version'],
                    cwd=working_dir,
                    check=False,
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    self.logger.info(f"pytest is installed system-wide: {result.stdout.strip()}")
                    return True
                else:
                    self.logger.warning("pytest is not installed system-wide")
                    return False
            except Exception as e:
                self.logger.warning(f"Failed to check if pytest is installed system-wide: {str(e)}")
                return False
                
        elif self.use_uv:
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
        
        # If no venv, install pytest system-wide
        if self.venv_path is None:
            self.logger.info("Installing pytest system-wide")
            try:
                # Install pytest using pip system-wide
                result = subprocess.run(
                    ['pip', 'install', 'pytest', '--user'],
                    cwd=working_dir,
                    check=False,
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    self.logger.info("pytest installed successfully system-wide")
                    return True
                else:
                    self.logger.error(f"Failed to install pytest system-wide: {result.stderr}")
                    return False
            except Exception as e:
                self.logger.error(f"Failed to install pytest system-wide: {str(e)}")
                return False
                
        elif self.use_uv:
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
                    
                    # Log tested files metadata if available
                    if self.test_metadata:
                        # Try multiple forms of the path
                        for path_form in [str(test_file), str(relative_path), test_file.name]:
                            if path_form in self.test_metadata:
                                tested_files = self.test_metadata[path_form].get("tested_files", [])
                                if tested_files:
                                    self.logger.info(f"Test file {relative_path} has {len(tested_files)} tested files")
                                break
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
    
    def _run_in_venv(self, command, cwd=None, env=None, timeout=None):
        """
        Run a command in the virtual environment.
        
        Args:
            command (list): Command to run.
            cwd (Path, optional): Working directory. If None, the repository root is used.
            env (dict, optional): Environment variables. If None, the current environment is used.
            timeout (int, optional): Timeout in seconds for the command. If None, no timeout is applied.
        
        Returns:
            dict: Dictionary with command result.
        """
        if cwd is None:
            cwd = self.repo_path
        
        if env is None:
            env = os.environ.copy()
        
        self.logger.info(f"Running command: {' '.join(command)}")
        
        # Get the path to the Python executable in the virtual environment or system Python
        python_path = self._get_python_path()
        
        # If no venv_path, and command is pytest, just use pytest directly
        if self.venv_path is None and command[0] == "pytest":
            try:
                # Try to find pytest in PATH
                result = subprocess.run(
                    ['which', 'pytest'] if sys.platform != 'win32' else ['where', 'pytest'],
                    check=False,
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0 and result.stdout.strip():
                    # Use pytest directly if found in PATH
                    command = [result.stdout.strip()] + command[1:]
                else:
                    # Fall back to python -m pytest
                    command = [str(python_path), "-m", "pytest"] + command[1:]
            except Exception:
                # If any error occurs, fall back to python -m pytest
                command = [str(python_path), "-m", "pytest"] + command[1:]
        elif command[0] == "pytest":
            # If the command starts with pytest (with venv), use python -m pytest instead
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
                text=True,
                timeout=timeout  # Apply timeout if provided
            )
            
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr
            }
        except subprocess.TimeoutExpired as e:
            self.logger.error(f"Command timed out after {timeout} seconds: {' '.join(command)}")
            return {
                "success": False,
                "error": f"Command timed out after {timeout} seconds",
                "returncode": -1,
                "stdout": e.stdout if e.stdout else "",
                "stderr": e.stderr if e.stderr else "",
                "timeout": True  # Add a flag to indicate timeout
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
        # If no venv, use system Python
        if self.venv_path is None:
            self.logger.info("Using system Python")
            python_path = Path(sys.executable)
            return python_path
        
        # Otherwise use venv Python
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
            Path: Path to the pytest executable, or None if not found.
        """
        # If no venv, try to find system pytest 
        if self.venv_path is None:
            try:
                # Check if pytest is available in PATH
                result = subprocess.run(
                    ['which', 'pytest'] if sys.platform != 'win32' else ['where', 'pytest'],
                    check=False,
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0 and result.stdout.strip():
                    pytest_path = Path(result.stdout.strip())
                    self.logger.info(f"Found system pytest at {pytest_path}")
                    return pytest_path
                else:
                    self.logger.warning("System pytest not found, falling back to using python -m pytest")
                    return None
            except Exception as e:
                self.logger.warning(f"Error finding system pytest: {str(e)}")
                return None
        
        # Otherwise check venv for pytest
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
        
        # Check if the virtual environment exists when it's supposed to
        if self.venv_path is not None and not self.venv_path.exists():
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
        
        # Get all test files (using provided list or by finding them)
        test_files = self.get_test_files()
        self.logger.info(f"Found {len(test_files)} test files")
        
        # Log the exact test files that will be run
        for i, test_file in enumerate(test_files):
            self.logger.info(f"Test file {i+1}: {test_file}")
            
        # If no test files found, return empty results
        if not test_files:
            self.logger.warning("No test files found")
            return {
                "tests_found": 0,
                "tests_passed": 0,
                "tests_failed": 0,
                "tests_skipped": 0,
                "test_results": [],
                "status": "skip"
            }
        
        # Try to get pytest module, install it if needed
        try:
            import pytest
        except ImportError:
            self.logger.info("pytest not found, attempting to install it")
            if not self.install_pytest():
                self.logger.error("Failed to install pytest, cannot run tests")
                raise RuntimeError("Failed to install pytest, cannot run tests")
            
            # Try importing again
            try:
                import pytest
            except ImportError:
                self.logger.error("Failed to import pytest after installation")
                raise RuntimeError("Failed to import pytest after installation")
        
        # Add common pytest imports
        import tempfile
        import xml.etree.ElementTree as ET
        import io
        import sys
        
        # Add the repository to the Python path temporarily
        sys.path.insert(0, str(self.repo_path))
        
        # Current directory to change back to
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
            
            # Create a temporary file for the JUnit XML output
            with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as xml_file:
                xml_path = xml_file.name
            
            self.logger.info(f"Using temporary XML file: {xml_path}")
            
            # Prepare pytest arguments
            pytest_args = [
                "-v",
                "--noconftest",
                "-o",
                "addopts=''"
                "--continue-on-collection-errors",
                f"--junitxml={xml_path}"
            ]
            
            # Add test files to pytest args
            pytest_args.extend(relative_test_files)
            
            # Capture console output
            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()
            
            # Set up timeout handler if needed
            if self.timeout:
                def timeout_handler():
                    self.logger.error(f"Test execution timed out after {self.timeout} seconds")
                    os._exit(1)
                
                timer = threading.Timer(self.timeout, timeout_handler)
                timer.daemon = True
                timer.start()
            
            # Run pytest and capture output
            try:
                # Redirect stdout and stderr
                old_stdout, old_stderr = sys.stdout, sys.stderr
                sys.stdout, sys.stderr = stdout_capture, stderr_capture
                
                # Run pytest
                self.logger.info(f"Running pytest with args: {pytest_args}")
                exit_code = pytest.main(pytest_args)
                
                # Get captured output
                stdout = stdout_capture.getvalue()
                stderr = stderr_capture.getvalue()
            finally:
                # Restore stdout and stderr
                sys.stdout, sys.stderr = old_stdout, old_stderr
                
                # Cancel timeout timer if it exists
                if self.timeout and 'timer' in locals():
                    timer.cancel()
            
            self.logger.info(f"Pytest stdout: {stdout}")
            self.logger.info(f"Pytest stderr: {stderr}")
            self.logger.info(f"Pytest exit code: {exit_code}")
            
            # Store raw output
            test_output = {
                "stdout": stdout,
                "stderr": stderr
            }
            
            # Initialize counters
            tests_found = 0
            tests_passed = 0
            tests_failed = 0
            tests_skipped = 0
            test_results = []
            file_results = []
            
            # Parse XML output if it exists
            try:
                if os.path.exists(xml_path) and os.path.getsize(xml_path) > 0:
                    self.logger.info(f"Parsing XML results from {xml_path}")
                    tree = ET.parse(xml_path)
                    root = tree.getroot()
                    
                    # Track file-level results
                    file_data = {}
                    
                    # Process test suites and test cases
                    for testsuite in root.findall('.//testsuite'):
                        # Get file name from testsuite attributes
                        file_name = testsuite.get('file') or testsuite.get('name')
                        if not file_name:
                            continue
                        
                        # Initialize file data
                        if file_name not in file_data:
                            file_data[file_name] = {
                                'passed': 0,
                                'failed': 0,
                                'skipped': 0,
                                'tests': []
                            }
                        
                        # Process individual test cases
                        for testcase in testsuite.findall('.//testcase'):
                            test_name = testcase.get('name')
                            class_name = testcase.get('classname')
                            
                            tests_found += 1
                            
                            # Create test result entry
                            test_result = {
                                'name': test_name,
                                'classname': class_name
                            }
                            
                            # Determine test status
                            if testcase.find('skipped') is not None:
                                tests_skipped += 1
                                file_data[file_name]['skipped'] += 1
                                test_result['status'] = 'skipped'
                                test_result['message'] = testcase.find('skipped').get('message', '')
                            elif testcase.find('failure') is not None:
                                tests_failed += 1
                                file_data[file_name]['failed'] += 1
                                test_result['status'] = 'failure'
                                test_result['message'] = testcase.find('failure').get('message', '')
                            elif testcase.find('error') is not None:
                                tests_failed += 1
                                file_data[file_name]['failed'] += 1
                                test_result['status'] = 'error'
                                test_result['message'] = testcase.find('error').get('message', '')
                            else:
                                tests_passed += 1
                                file_data[file_name]['passed'] += 1
                                test_result['status'] = 'passed'
                                test_result['message'] = ''
                            
                            # Add to file's test list
                            file_data[file_name]['tests'].append(test_result)
                    
                    # Create file-level results
                    for file_name, data in file_data.items():
                        # Get tested_files metadata if available
                        tested_files = []
                        for path_form in [file_name, os.path.basename(file_name)]:
                            if path_form in self.test_metadata:
                                tested_files = self.test_metadata[path_form].get("tested_files", [])
                                break
                        
                        # Remove duplicates while preserving order
                        if tested_files:
                            seen = set()
                            unique_tested_files = []
                            for item in tested_files:
                                if item not in seen:
                                    seen.add(item)
                                    unique_tested_files.append(item)
                            
                            # Log if duplicates were found and removed
                            if len(unique_tested_files) < len(tested_files):
                                self.logger.info(f"Removed {len(tested_files) - len(unique_tested_files)} duplicate entries from tested_files for {file_name}")
                            
                            # Update the metadata and our local variable
                            if path_form in self.test_metadata:
                                self.test_metadata[path_form]["tested_files"] = unique_tested_files
                            tested_files = unique_tested_files
                        
                        # Determine file status
                        file_status = "skipped"
                        if data['passed'] > 0 and data['failed'] > 0:
                            file_status = "partial_success"
                            message = f"Some tests passed ({data['passed']}), some failed ({data['failed']})"
                            self.logger.info(f"File {file_name} has partial success: {message}")
                        elif data['failed'] > 0:
                            file_status = "failure"
                            message = f"All tests failed ({data['failed']})"
                        elif data['passed'] > 0:
                            file_status = "success"
                            message = f"All tests passed ({data['passed']})"
                        elif data['skipped'] > 0:
                            file_status = "skipped"
                            message = f"All tests skipped ({data['skipped']})"
                        else:
                            message = "No tests run"
                        
                        # Add file result
                        file_result = {
                            "path": file_name,
                            "name": file_name,
                            "status": file_status,
                            "message": message,
                            "tested_files": tested_files,
                            "tests": data['tests'],
                            "summary": {
                                "passed_tests": data['passed'],
                                "failed_tests": data['failed'],
                                "skipped_tests": data['skipped']
                            }
                        }
                        
                        file_results.append(file_result)
                        
                        # Add to test_results for backwards compatibility
                        test_results.append({
                            "name": file_name,
                            "status": file_status,
                            "message": message,
                            "tested_files": tested_files,
                            # Include all test details in a single field
                            "tests": data['tests'],
                            "summary": {
                                "passed_tests": data['passed'],
                                "failed_tests": data['failed'],
                                "skipped_tests": data['skipped']
                            }
                        })
                        self.logger.info(f"Collected {len(data['tests'])} individual tests for {file_name}")
                else:
                    self.logger.warning(f"XML file not found or empty: {xml_path}")
                    # Fall back to parsing stdout
                    tests_found, tests_passed, tests_failed, tests_skipped, test_results = self._parse_test_results(stdout, stderr)
                    
                    # Create basic file results for backwards compatibility
                    for result in test_results:
                        file_results.append({
                            "path": result["name"],
                            "name": result["name"],
                            "status": result["status"],
                            "message": result.get("message", ""),
                            "tested_files": result.get("tested_files", []),
                            "tests": []  # Add empty tests array for consistency
                        })
            except Exception as e:
                self.logger.error(f"Error parsing test results: {str(e)}")
                # Fall back to parsing stdout
                tests_found, tests_passed, tests_failed, tests_skipped, test_results = self._parse_test_results(stdout, stderr)
                
                # Create basic file results for backwards compatibility
                for result in test_results:
                    file_results.append({
                        "path": result["name"],
                        "name": result["name"],
                        "status": result["status"],
                        "message": result.get("message", ""),
                        "tested_files": result.get("tested_files", []),
                        "tests": []  # Add empty tests array for consistency
                    })
            
            # Determine overall status
            status = "skipped"
            if tests_found == 0:
                status = "skipped"
            elif tests_passed > 0 and tests_failed == 0:
                status = "success"
            elif tests_passed > 0 and tests_failed > 0:
                status = "partial_success"
            elif tests_passed == 0 and tests_failed > 0:
                status = "failure"
            
            # Count file status types
            files_with_partial_success = sum(1 for r in file_results if r["status"] == "partial_success")
            files_with_success = sum(1 for r in file_results if r["status"] == "success")
            files_with_failure = sum(1 for r in file_results if r["status"] == "failure")
            files_with_skipped = sum(1 for r in file_results if r["status"] == "skipped")
            
            # Create summary
            summary = {
                "total_files": len(file_results),
                "passed_files": files_with_success,
                "partial_files": files_with_partial_success,
                "failed_files": files_with_failure,
                "skipped_files": files_with_skipped,
                "passed_tests": tests_passed,
                "failed_tests": tests_failed,
                "skipped_tests": tests_skipped
            }
            
            # Extract individual test results across all files for easier access
            individual_test_results = []
            for file_result in file_results:
                file_path = file_result["path"]
                # Try to extract test details from the file result
                if "tests" in file_result and "details" in file_result["tests"]:
                    for test_detail in file_result["tests"]["details"]:
                        # Create a simplified test result entry with file information
                        individual_test_results.append({
                            "file_path": file_path,
                            "name": test_detail.get("name", ""),
                            "classname": test_detail.get("classname", ""),
                            "status": test_detail.get("status", ""),
                            "message": test_detail.get("message", "")
                        })
                
                # Also make sure the test_results array has individual test names
                # for backwards compatibility
                if file_path in [r["name"] for r in test_results]:
                    for r in test_results:
                        if r["name"] == file_path:
                            # Check if we need to populate the tests list
                            if not r.get("tests"):
                                # Find individual tests for this file
                                file_tests = [
                                    {
                                        "name": t["name"],
                                        "classname": t["classname"],
                                        "status": t["status"],
                                        "message": t["message"]
                                    }
                                    for t in individual_test_results if t["file_path"] == file_path
                                ]
                                r["tests"] = file_tests
                                
                                # Make sure summary is updated too
                                if "summary" not in r:
                                    r["summary"] = {}
                                
                                passed_count = sum(1 for t in file_tests if t["status"] == "passed")
                                failed_count = sum(1 for t in file_tests if t["status"] in ["failure", "error"])
                                skipped_count = sum(1 for t in file_tests if t["status"] == "skipped")
                                
                                r["summary"].update({
                                    "passed_tests": passed_count,
                                    "failed_tests": failed_count,
                                    "skipped_tests": skipped_count
                                })
            
            self.logger.info(f"Test summary: {summary}")
            self.logger.info(f"Individual tests: {len(individual_test_results)}")
            
            return {
                "tests_found": tests_found,
                "tests_passed": tests_passed,
                "tests_failed": tests_failed,
                "tests_skipped": tests_skipped,
                "test_results": test_results,
                "test_files": file_results,
                "individual_tests": individual_test_results,  # Add individual test results
                "summary": summary,
                "status": status,
                "test_output": test_output
            }
        
        except Exception as e:
            self.logger.error(f"Error running tests: {str(e)}")
            return {
                "tests_found": 0,
                "tests_passed": 0,
                "tests_failed": 0,
                "tests_skipped": 0,
                "test_results": [],
                "status": "error",
                "error": str(e)
            }
        finally:
            # Restore the original directory and path
            os.chdir(current_dir)
            if str(self.repo_path) in sys.path:
                sys.path.remove(str(self.repo_path))

    def _parse_test_results(self, stdout, stderr):
        """Parse test results from stdout and stderr."""
        tests_found = 0
        tests_passed = 0
        tests_failed = 0
        tests_skipped = 0
        test_results = []
        test_file_dict = {}
        file_to_tests = {}
        executed_tests = set()

        # Track collection errors separately from execution failures
        collection_errors = []
        execution_errors = []

        # First check for collection errors
        for line in stderr.splitlines():
            if "ImportError" in line or "ModuleNotFoundError" in line:
                collection_errors.append(line)
            elif "ERROR collecting" in line:
                collection_errors.append(line)
            elif "ERROR" in line and "during collection" in line:
                collection_errors.append(line)

        # Process stdout for test results
        for line in stdout.splitlines():
            # Look for pytest result lines that include file names
            if ' PASSED ' in line or ' FAILED ' in line or ' SKIPPED ' in line or ' ERROR ' in line:
                try:
                    # Extract file name and test name
                    parts = line.split(' ', 1)[0].strip()
                    if '::' in parts:
                        file_name, test_name = parts.split('::', 1)
                    else:
                        file_name = parts
                        test_name = parts  # Use file name as test name if no specific test
                    
                    # Initialize file tracking if not already done
                    if file_name not in file_to_tests:
                        file_to_tests[file_name] = {
                            'passed': [],
                            'failed': [],
                            'skipped': [],
                            'file_path': file_name
                        }
                    
                    # Track this test result
                    if ' PASSED ' in line:
                        file_to_tests[file_name]['passed'].append(test_name)
                    elif ' FAILED ' in line or ' ERROR ' in line:
                        file_to_tests[file_name]['failed'].append(test_name)
                    elif ' SKIPPED ' in line:
                        file_to_tests[file_name]['skipped'].append(test_name)
                except Exception as e:
                    self.logger.warning(f"Error parsing test result line: {line}, error: {str(e)}")

        # If we found test files through the more detailed tracking, use that
        if file_to_tests:
            self.logger.info(f"Found {len(file_to_tests)} test files with detailed results")
            
            for file_name, tests in file_to_tests.items():
                # Determine file status based on test results
                has_passed = len(tests['passed']) > 0
                has_failed = len(tests['failed']) > 0
                has_skipped = len(tests['skipped']) > 0
                
                # Get tested_files metadata if available
                tested_files = []
                for path_form in [file_name, os.path.basename(file_name)]:
                    if path_form in self.test_metadata:
                        tested_files = self.test_metadata[path_form].get("tested_files", [])
                        break
                
                status = "skipped"
                message = ""
                
                if has_passed and has_failed:
                    status = "partial_success"
                    message = f"Some tests passed ({len(tests['passed'])}), some failed ({len(tests['failed'])})"
                    self.logger.info(f"File {file_name} has partial success: {message}")
                elif has_failed:
                    status = "failure"
                    message = f"All tests failed ({len(tests['failed'])})"
                elif has_passed:
                    status = "success"
                    message = f"All tests passed ({len(tests['passed'])})"
                elif has_skipped:
                    status = "skipped"
                    message = f"All tests skipped ({len(tests['skipped'])})"
                
                test_results.append({
                    "name": file_name,
                    "status": status,
                    "message": message,
                    "tested_files": tested_files,
                    "tests": {
                        "passed": len(tests['passed']),
                        "failed": len(tests['failed']),
                        "skipped": len(tests['skipped'])
                    }
                })
        else:
            # Fall back to the original method
            self.logger.warning("No test files found with detailed tracking, falling back to original method")
            
            # Create test results using the dictionary
            for test_name, info in test_file_dict.items():
                # Get tested_files metadata if available
                tested_files = []
                # Check multiple forms of the path to find metadata
                for path_form in [test_name, str(info["file"]), os.path.basename(test_name)]:
                    if path_form in self.test_metadata:
                        tested_files = self.test_metadata[path_form].get("tested_files", [])
                        break
                
                # Create result with appropriate status and include tested_files
                result_entry = {
                    "name": test_name,
                    "tested_files": tested_files
                }
                
                # Determine if this test file was actually executed
                was_executed = any(test_name in executed for executed in executed_tests)

                # Check if this file had collection errors
                file_had_collection_errors = any(test_name in error for error in collection_errors)

                # For each test file, track if it had passed and failed tests 
                has_passed_tests = False
                has_failed_tests = False
                for line in stdout.splitlines():
                    if test_name in line:
                        if 'PASSED' in line:
                            has_passed_tests = True
                        elif 'FAILED' in line or 'ERROR' in line:
                            has_failed_tests = True
                
                # Assign status based on individual file results
                if file_had_collection_errors:
                    # File had collection errors - mark as failure
                    result_entry.update({
                        "status": "failure",
                        "message": "Test collection failed - import or setup errors"
                    })
                    tests_failed += 1
                elif has_passed_tests and has_failed_tests:
                    # File has both passed and failed tests - partial success
                    result_entry.update({
                        "status": "partial_success",
                        "message": "Some tests passed, some failed in this file"
                    })
                elif info["failed"]:
                    result_entry.update({
                        "status": "failure",
                        "message": info["message"] or "Test failed during execution"
                    })
                elif has_passed_tests:
                    result_entry.update({
                        "status": "success",
                        "message": ""
                    })
                elif info["skipped"]:
                    result_entry.update({
                        "status": "skipped",
                        "message": "Test was skipped - no tests ran"
                    })
                elif info["uncollected"] and not was_executed and not file_had_collection_errors:
                    # No tests could be collected but no errors - mark as skipped
                    result_entry.update({
                        "status": "skipped",
                        "message": "No test functions found in this file"
                    })
                else:
                    result_entry.update({
                        "status": "success",
                        "message": ""
                    })
                    
                test_results.append(result_entry)

        return tests_found, tests_passed, tests_failed, tests_skipped, test_results 