"""
Test runner for Repo2Run.

This module handles finding and running tests in a repository.
"""

import logging
import os
import re
import subprocess
from pathlib import Path


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
                # Get current working directory
                cwd = os.getcwd()
                self.logger.info(f"Current working directory: {cwd}")
                
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
            result = subprocess.run(
                ['pytest', '--version'],
                check=False,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                self.logger.info(f"pytest is installed: {result.stdout.strip()}")
                return True
            else:
                self.logger.warning(f"pytest is not installed: {result.stderr.strip()}")
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
        
        python_path = self.venv_path / 'bin' / 'python'
        
        try:
            # Get Python version to determine compatible pytest version
            version_result = subprocess.run(
                [str(python_path), '-c', 'import sys; print(sys.version_info.major, sys.version_info.minor)'],
                check=False,
                capture_output=True,
                text=True
            )
            
            if version_result.returncode != 0:
                self.logger.error(f"Failed to determine Python version: {version_result.stderr}")
                return False
                
            python_version = version_result.stdout.strip().split()
            if len(python_version) == 2:
                major, minor = map(int, python_version)
                
                # For Python 3.12+, we need pytest 7.4.0 or newer
                pytest_spec = "pytest>=7.4.0" if major == 3 and minor >= 12 else "pytest"
                self.logger.info(f"Installing {pytest_spec} for Python {major}.{minor}")
                
                # Install pytest using uv
                result = subprocess.run(
                    ['pip', 'install', pytest_spec],
                    check=False,
                    capture_output=True,
                    text=True,
                    env=dict(os.environ, VIRTUAL_ENV=str(self.venv_path))
                )
                
                if result.returncode == 0:
                    self.logger.info("pytest installed successfully using uv")
                    return True
                else:
                    self.logger.error(f"Failed to install pytest using uv: {result.stderr}")
                    return False
            else:
                self.logger.error(f"Unexpected Python version format: {version_result.stdout}")
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
                
        try:
            result = subprocess.run(
                ['pytest', '--collect-only', '-q', '--disable-warnings'],
                cwd=self.repo_path,
                check=False,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0 or result.returncode == 5:
                # Extract test cases using regex
                test_case_pattern = re.compile(r'^([\w/]+\.py::[\w_]+)$', re.MULTILINE)
                test_cases = test_case_pattern.findall(result.stdout)
                
                self.logger.info(f"Collected {len(test_cases)} test cases")
                return test_cases
            else:
                self.logger.warning(f"Failed to collect test cases: {result.stderr}")
                return []
        except Exception as e:
            self.logger.warning(f"Failed to collect test cases: {str(e)}")
            return []
    
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
            # # Verify installation was successful
            # if not self.check_pytest():
            #     self.logger.error("pytest installation verification failed. Cannot run tests.")
            #     return {
            #         "status": "error",
            #         "message": "pytest installation verification failed",
            #         "tests_found": 0,
            #         "tests_passed": 0,
            #         "tests_failed": 0,
            #         "tests_skipped": 0,
            #         "test_results": []
            #     }
        
        # Collect test cases
        test_cases = self.collect_tests()
        
        if not test_cases:
            self.logger.info("No test cases found")
            
            # Print out current directory and file listing for debugging
            try:
                # Get current working directory
                cwd = os.getcwd()
                self.logger.info(f"Current working directory: {cwd}")
                
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
        
        # Run tests        
        try:
            result = subprocess.run(
                ['pytest', '-v'],
                cwd=self.repo_path,
                check=False,
                capture_output=True,
                text=True
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