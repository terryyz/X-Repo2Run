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
        
        # Find test files in tests/ directory
        test_files.extend(self.repo_path.glob("**/tests/**/*test*.py"))
        test_files.extend(self.repo_path.glob("**/test/**/*test*.py"))
        
        # Find test files in the root directory
        test_files.extend(self.repo_path.glob("test_*.py"))
        test_files.extend(self.repo_path.glob("*_test.py"))
        
        # Remove duplicates and sort
        test_files = sorted(set(test_files))
        
        self.logger.info(f"Found {len(test_files)} test files")
        return test_files
    
    def check_pytest(self):
        """
        Check if pytest is installed in the virtual environment.
        
        Returns:
            bool: True if pytest is installed, False otherwise.
        """
        self.logger.info("Checking if pytest is installed")
        
        python_path = self.venv_path / 'bin' / 'python'
        
        try:
            result = subprocess.run(
                [str(python_path), '-m', 'pytest', '--version'],
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
            # Install pytest using uv
            result = subprocess.run(
                ['uv', 'pip', 'install', 'pytest'],
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
        
        python_path = self.venv_path / 'bin' / 'python'
        
        try:
            result = subprocess.run(
                [str(python_path), '-m', 'pytest', '--collect-only', '-q', '--disable-warnings'],
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
            # Verify installation was successful
            if not self.check_pytest():
                self.logger.error("pytest installation verification failed. Cannot run tests.")
                return {
                    "status": "error",
                    "message": "pytest installation verification failed",
                    "tests_found": 0,
                    "tests_passed": 0,
                    "tests_failed": 0,
                    "tests_skipped": 0,
                    "test_results": []
                }
        
        # Collect test cases
        test_cases = self.collect_tests()
        
        if not test_cases:
            self.logger.info("No test cases found")
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
        python_path = self.venv_path / 'bin' / 'python'
        
        try:
            result = subprocess.run(
                [str(python_path), '-m', 'pytest', '-v'],
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