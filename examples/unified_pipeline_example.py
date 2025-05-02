#!/usr/bin/env python3
# Copyright (c) 2023-2024 Repo2Run Contributors

"""
Example of using the Unified Pipeline API programmatically.

This example demonstrates how to:
1. Set up a list of repositories
2. Extract and unify dependencies across all repositories
3. Create a unified virtual environment
4. Run tests for each repository
5. Filter repositories that pass all tests or have no tests
"""

import os
import sys
import logging
from pathlib import Path
import json
from typing import List, Dict, Set, Tuple, Any

# Make sure repo2run package is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from repo2run.utils.repo_manager import RepoManager
from repo2run.utils.dependency_extractor import DependencyExtractor
from repo2run.utils.dependency_installer import DependencyInstaller
from repo2run.utils.test_runner import TestRunner
from repo2run.utils.logger import configure_process_logging

# Configure logging
logger = configure_process_logging(verbose=True)

def main():
    # Parameters
    output_dir = Path("./unified_output")
    repo_list_file = Path("./repos.txt")
    use_uv = False  # Set to True to use UV for dependency management
    timeout = 1800  # 30 minutes
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Using output directory: {output_dir}")
    
    # 1. Load repository list
    repo_infos = []
    try:
        with open(repo_list_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        full_name, sha = line.split()
                        repo_infos.append((full_name, sha))
                    except ValueError:
                        logger.warning(f"Skipping invalid line: {line}")
    except Exception as e:
        logger.error(f"Error reading repository list file: {e}")
        return 1
    
    logger.info(f"Loaded {len(repo_infos)} repositories from {repo_list_file}")
    
    # 2. Extract dependencies from all repositories
    all_dependencies = set()
    repo_req_data = {}
    
    for repo_info in repo_infos:
        full_name, sha = repo_info
        repo_id = f"{full_name}@{sha}"
        
        try:
            # Clone repository
            repo_manager = RepoManager(output_dir=output_dir, logger=logger)
            working_dir = repo_manager.clone_repository(full_name, sha)
            
            # Extract dependencies
            logger.info(f"Extracting dependencies from {repo_id}")
            dependency_extractor = DependencyExtractor(working_dir, logger=logger)
            requirements_dict = dependency_extractor.extract_all_requirements()
            
            # Unify requirements for this repository
            unified_requirements = dependency_extractor.unify_requirements(requirements_dict)
            logger.info(f"Found {len(unified_requirements)} unique requirements for {repo_id}")
            
            # Extract package names without version specifiers
            packages = set()
            for req in unified_requirements:
                # Skip empty lines and comments
                if not req or req.startswith('#'):
                    continue
                
                # Extract package name (remove version specifiers)
                import re
                match = re.match(r'^([a-zA-Z0-9_\-\.]+)([<>=!~].+)?$', req)
                if match:
                    package_name = match.group(1).lower()
                    packages.add(package_name)
            
            # Update global dependencies set
            all_dependencies.update(packages)
            
            # Store in repo_req_data
            repo_req_data[repo_id] = list(packages)
            
        except Exception as e:
            logger.error(f"Failed to extract dependencies from {repo_id}: {str(e)}")
    
    # Save repo requirements to file
    repo_req_path = output_dir / "repo_req.json"
    with open(repo_req_path, 'w') as f:
        json.dump(repo_req_data, f, indent=2)
    
    # Save all dependencies to requirements.txt
    requirements_path = output_dir / "requirements.txt"
    with open(requirements_path, 'w') as f:
        for dep in sorted(all_dependencies):
            f.write(f"{dep}\n")
    
    logger.info(f"Found {len(all_dependencies)} unique dependencies across all repositories")
    logger.info(f"Requirements saved to {requirements_path}")
    logger.info(f"Repository requirements saved to {repo_req_path}")
    
    # 3. Create unified virtual environment
    venv_path = output_dir / "unified_venv"
    
    if venv_path.exists():
        logger.info(f"Using existing virtual environment at {venv_path}")
    else:
        # Create virtual environment
        if use_uv:
            logger.info(f"Creating virtual environment with UV at {venv_path}")
            try:
                import subprocess
                subprocess.run(
                    ['uv', 'venv', str(venv_path)],
                    check=True,
                    capture_output=True,
                    text=True
                )
            except Exception as e:
                logger.error(f"Failed to create virtual environment with UV: {str(e)}")
                return 1
        else:
            logger.info(f"Creating virtual environment with venv at {venv_path}")
            try:
                import venv
                venv.create(venv_path, with_pip=True)
            except Exception as e:
                logger.error(f"Failed to create virtual environment with venv: {str(e)}")
                return 1
    
    # 4. Install dependencies
    install_status = {}
    dependencies_list = sorted(all_dependencies)
    
    for dep in dependencies_list:
        try:
            if use_uv:
                # Use UV to install the dependency
                import subprocess
                result = subprocess.run(
                    ['uv', 'pip', 'install', dep],
                    cwd=venv_path,
                    check=False,
                    capture_output=True,
                    text=True
                )
            else:
                # Get pip path
                if sys.platform == 'win32':
                    pip_path = venv_path / 'Scripts' / 'pip.exe'
                else:
                    pip_path = venv_path / 'bin' / 'pip'
                
                # Use pip to install the dependency
                import subprocess
                result = subprocess.run(
                    [str(pip_path), 'install', dep],
                    check=False,
                    capture_output=True,
                    text=True
                )
            
            success = result.returncode == 0
            install_status[dep] = {
                "success": success,
                "error": result.stderr if not success else None
            }
            
            if not success:
                logger.warning(f"Failed to install {dep}: {result.stderr}")
        
        except Exception as e:
            logger.error(f"Error installing {dep}: {str(e)}")
            install_status[dep] = {
                "success": False,
                "error": str(e)
            }
    
    # Save installation status to file
    install_status_path = output_dir / "install_status.json"
    with open(install_status_path, 'w') as f:
        json.dump(install_status, f, indent=2)
    
    # Count successful installations
    success_count = sum(1 for status in install_status.values() if status["success"])
    logger.info(f"Successfully installed {success_count} out of {len(all_dependencies)} dependencies")
    logger.info(f"Installation status saved to {install_status_path}")
    
    # 5. Run tests for each repository
    all_results = []
    records_path = output_dir / "records.jsonl"
    
    for repo_info in repo_infos:
        full_name, sha = repo_info
        repo_id = f"{full_name}@{sha}"
        
        logger.info(f"Testing repository: {repo_id}")
        
        try:
            # Clone repository
            repo_manager = RepoManager(output_dir=output_dir, logger=logger)
            working_dir = repo_manager.clone_repository(full_name, sha)
            
            # Install the package in development mode
            try:
                if sys.platform == 'win32':
                    pip_path = venv_path / 'Scripts' / 'pip.exe'
                else:
                    pip_path = venv_path / 'bin' / 'pip'
                
                import subprocess
                
                # Install Cython first
                subprocess.run(
                    [str(pip_path), 'install', 'Cython'],
                    check=True,
                    capture_output=True,
                    text=True
                )
                
                # Install package in development mode
                subprocess.run(
                    [str(pip_path), 'install', '-e', '.'],
                    cwd=working_dir,
                    check=True,
                    capture_output=True,
                    text=True
                )
                logger.info(f"Successfully installed {repo_id} in development mode")
            except Exception as e:
                logger.warning(f"Failed to install {repo_id} in development mode: {str(e)}")
            
            # Run tests
            test_runner = TestRunner(working_dir, venv_path=venv_path, use_uv=use_uv,
                                    logger=logger, timeout=timeout)
            
            # Find tests
            test_files = test_runner.find_tests()
            
            result_data = {
                "repository": repo_id,
                "status": "running",
                "tests": {
                    "found": 0,
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "details": []
                }
            }
            
            if not test_files:
                logger.info(f"No tests found for {repo_id}. Marking as 'skip'")
                result_data["status"] = "skip"
            else:
                logger.info(f"Found {len(test_files)} test files for {repo_id}")
                
                # Run tests
                test_results = test_runner.run_tests()
                
                # Parse test results
                import re
                has_failures = False
                failure_count = 0
                success_count = 0
                skip_count = 0
                total_test_cases = 0
                
                # First try to get counts from pytest summary line
                for test_detail in test_results.get("test_results", []):
                    message = test_detail.get("message", "")
                    
                    # Look for pytest summary line like "X failed, Y passed, Z warnings in T.TTs"
                    summary_match = re.search(r'(\d+) failed, (\d+) passed(?:, (\d+) skipped)?.* in \d+\.\d+s', message)
                    if summary_match:
                        failure_count = int(summary_match.group(1))
                        success_count = int(summary_match.group(2))
                        skip_count = int(summary_match.group(3)) if summary_match.group(3) else 0
                        total_test_cases = failure_count + success_count + skip_count
                        has_failures = failure_count > 0
                        break
                
                # If no summary line found, fall back to counting individual results
                if total_test_cases == 0:
                    for test_detail in test_results.get("test_results", []):
                        message = test_detail.get("message", "")
                        status = test_detail.get("status", "")
                        
                        if status == "failure" or "ERROR" in message or "FAILED" in message:
                            has_failures = True
                            # Count individual failures
                            failure_matches = len(re.findall(r'(ERROR|FAILED)', message))
                            failure_count += failure_matches if failure_matches > 0 else 1
                        elif status == "success":
                            # Count individual successes (PASSED)
                            success_matches = len(re.findall(r'PASSED', message))
                            success_count += success_matches if success_matches > 0 else 1
                        elif status == "skipped" or "SKIPPED" in message:
                            skip_matches = len(re.findall(r'SKIPPED', message))
                            skip_count += skip_matches if skip_matches > 0 else 1
                    
                    total_test_cases = failure_count + success_count + skip_count
                
                # Store test results
                result_data["tests"]["found"] = total_test_cases
                result_data["tests"]["passed"] = success_count
                result_data["tests"]["failed"] = failure_count
                result_data["tests"]["skipped"] = skip_count
                result_data["tests"]["details"] = test_results.get("test_results", [])
                
                # Determine status
                if total_test_cases == 0:
                    result_data["status"] = "skip"
                    logger.info(f"No test cases found for {repo_id}. Marking as 'skip'")
                elif failure_count > 0:
                    if success_count > 0:
                        result_data["status"] = "partial_success"
                        logger.info(f"Some tests passed ({success_count}), some failed ({failure_count}) for {repo_id}. Marking as 'partial_success'")
                    else:
                        result_data["status"] = "failure"
                        logger.info(f"All tests failed ({failure_count}) for {repo_id}. Marking as 'failure'")
                else:
                    result_data["status"] = "success"
                    logger.info(f"All tests passed ({success_count}) for {repo_id}. Marking as 'success'")
            
            # Add result to all_results
            all_results.append(result_data)
            
            # Append to records.jsonl
            with open(records_path, 'a') as f:
                f.write(json.dumps(result_data) + '\n')
            
        except Exception as e:
            logger.error(f"Error testing {repo_id}: {str(e)}")
            
            # Record the error
            result_data = {
                "repository": repo_id,
                "status": "error",
                "error": str(e)
            }
            
            all_results.append(result_data)
            
            # Append to records.jsonl
            with open(records_path, 'a') as f:
                f.write(json.dumps(result_data) + '\n')
    
    # 6. Filter repositories that pass all tests or have no tests
    successful_repos = []
    
    for result in all_results:
        status = result.get("status", "")
        repo_id = result.get("repository", "")
        
        if status == "success" or status == "skip":
            successful_repos.append(repo_id)
    
    # Save the list of successful repositories
    successful_repos_path = output_dir / "successful_repos.json"
    with open(successful_repos_path, 'w') as f:
        json.dump(successful_repos, f, indent=2)
    
    logger.info(f"Found {len(successful_repos)} repositories that pass all tests or have no tests")
    logger.info(f"Successful repositories saved to {successful_repos_path}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main()) 