#!/usr/bin/env python3
# Copyright (c) 2023-2024 Repo2Run Contributors

"""
Unified Pipeline for Repo2Run.

This script implements a pipeline that:
1. Analyzes dependencies across all repositories and creates a union set
2. Installs dependencies in a single virtual environment
3. Runs tests for each repository and identifies those that pass all tests or have no tests

Usage:
    # Process repositories from a list file
    python -m repo2run.unified_pipeline --repo-list repos.txt --output-dir output_path [--overwrite] [--verbose]

    # Process local directories from a list file
    python -m repo2run.unified_pipeline --local-list dirs.txt --output-dir output_path [--overwrite] [--verbose]

Options:
    --repo-list FILE       Text file containing list of repositories (format: user/repo sha)
    --local-list FILE      Text file containing list of local directories
    --output-dir DIR       Directory to store output files (default: output)
    --workspace-dir DIR    Directory to use as workspace (default: temporary directory)
    --timeout SECONDS      Timeout in seconds (default: 7200 - 2 hours)
    --verbose              Enable verbose logging
    --overwrite            Overwrite existing output directory if it exists
    --use-uv               Use UV for dependency management (default: False, use pip/venv)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import datetime
import logging
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional, Any
import tempfile
import re
import concurrent.futures
from tqdm import tqdm

from repo2run.utils.repo_manager import RepoManager
from repo2run.utils.dependency_extractor import DependencyExtractor
from repo2run.utils.dependency_installer import DependencyInstaller
from repo2run.utils.test_runner import TestRunner
from repo2run.utils.logger import configure_process_logging


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Unified pipeline for analyzing dependencies and running tests across multiple repositories.'
    )
    
    # Create mutually exclusive group for repo source
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        '--repo-list',
        type=str,
        metavar='FILE',
        help='Text file containing list of repositories (format: user/repo sha)'
    )
    source_group.add_argument(
        '--local-list',
        type=str,
        metavar='FILE',
        help='Text file containing list of local directories'
    )
    
    # Additional arguments
    parser.add_argument(
        '--output-dir', 
        type=str, 
        default='output',
        help='Directory to store output files (default: output)'
    )
    parser.add_argument(
        '--workspace-dir',
        type=str,
        default=None,
        help='Directory to use as workspace (default: temporary directory)'
    )
    parser.add_argument(
        '--timeout', 
        type=int, 
        default=7200,
        help='Timeout in seconds (default: 7200 - 2 hours)'
    )
    parser.add_argument(
        '--verbose', 
        action='store_true',
        help='Enable verbose logging'
    )
    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='Overwrite existing output directory if it exists'
    )
    parser.add_argument(
        '--use-uv',
        action='store_true',
        help='Use UV for dependency management (default: False, use pip/venv)'
    )
    parser.add_argument(
        '--max-workers',
        type=int,
        default=4,
        help='Maximum number of worker threads for parallel processing (default: 4)'
    )
    
    return parser.parse_args()


def load_repositories(args):
    """
    Load repositories from either a repo list or a local directory list.
    
    Args:
        args: Command line arguments
    
    Returns:
        list: List of repositories to process
            For repo-list: [(full_name, sha), ...]
            For local-list: [path, ...]
    """
    logger = logging.getLogger(__name__)
    
    if args.repo_list:
        repo_infos = []
        try:
            with open(args.repo_list, 'r') as f:
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
            return []
        
        logger.info(f"Loaded {len(repo_infos)} repositories from {args.repo_list}")
        return repo_infos
    
    elif args.local_list:
        local_paths = []
        try:
            with open(args.local_list, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        # Convert string paths to Path objects
                        # These will be processed directly without copying to output_dir
                        path = Path(line)
                        local_paths.append(path)
        except Exception as e:
            logger.error(f"Error reading local list file: {e}")
            return []
        
        logger.info(f"Loaded {len(local_paths)} local directories from {args.local_list}")
        return local_paths
    
    return []


def extract_dependencies(repo_info, output_dir, args, repo_req_data):
    """
    Extract dependencies from a single repository.
    
    Args:
        repo_info: Repository information (tuple or Path)
        output_dir: Output directory
        args: Command line arguments
        repo_req_data: Dictionary to store repository requirements
    
    Returns:
        tuple: (repo_identifier, requirements)
    """
    # Configure logging for each process
    logger = logging.getLogger(__name__)
    
    # Initialize repository manager
    repo_manager = RepoManager(output_dir=output_dir, logger=logger)
    
    try:
        # Clone or set up local repository
        if isinstance(repo_info, tuple):
            full_name, sha = repo_info
            working_dir = repo_manager.clone_repository(full_name, sha)
            repo_id = f"{full_name}@{sha}"
        else:
            local_path = Path(repo_info) if not isinstance(repo_info, Path) else repo_info
            # Use the repository directly without copying
            working_dir = repo_manager.use_local_repository(local_path)
            repo_id = str(local_path.resolve())
        
        # Extract dependencies
        dependency_extractor = DependencyExtractor(working_dir, logger=logger)
        requirements_dict = dependency_extractor.extract_all_requirements()
        
        # Unify requirements for this repository
        unified_requirements = dependency_extractor.unify_requirements(requirements_dict)
        
        # Extract package names without version specifiers
        packages = set()
        for req in unified_requirements:
            # Skip empty lines and comments
            if not req or req.startswith('#'):
                continue
            
            # Extract package name (remove version specifiers)
            match = re.match(r'^([a-zA-Z0-9_\-\.]+)([<>=!~].+)?$', req)
            if match:
                package_name = match.group(1).lower()
                packages.add(package_name)
        
        # Store in repo_req_data (if it's a Manager dict)
        if hasattr(repo_req_data, '__setitem__'):
            repo_req_data[repo_id] = list(packages)
        
        return repo_id, packages
    
    except Exception as e:
        logger.error(f"Failed to extract dependencies from {repo_info}: {str(e)}")
        return None, set()


def analyze_dependencies_parallel(repositories, output_dir, args):
    """
    Analyze dependencies across all repositories in parallel.
    
    Args:
        repositories: List of repositories
        output_dir: Output directory
        args: Command line arguments
    
    Returns:
        tuple: (all_dependencies, repo_req_data)
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Starting dependency analysis for {len(repositories)} repositories")
    
    # Dictionary to store requirements by repository (use a thread-safe manager)
    from multiprocessing import Manager
    manager = Manager()
    repo_req_data = manager.dict()
    
    # Set to store all unique dependencies (we'll merge later)
    dependencies_by_repo = []
    
    # Print summary of repositories being processed
    if isinstance(repositories[0], tuple):
        # GitHub repositories
        logger.info("Repositories to process:")
        for idx, (full_name, sha) in enumerate(repositories[:10], 1):
            logger.info(f"  {idx}. {full_name}@{sha}")
        if len(repositories) > 10:
            logger.info(f"  ... and {len(repositories) - 10} more repositories")
    else:
        # Local directories
        logger.info("Local directories to process:")
        for idx, path in enumerate(repositories[:10], 1):
            path_obj = path if isinstance(path, Path) else Path(path)
            logger.info(f"  {idx}. {path_obj}")
        if len(repositories) > 10:
            logger.info(f"  ... and {len(repositories) - 10} more directories")
    
    # Increase default max_workers for better parallelism
    max_workers = args.max_workers
    if max_workers <= 4 and len(repositories) > 10:
        # Use more workers for larger numbers of repositories
        # but don't exceed available CPU cores
        import multiprocessing
        available_cores = multiprocessing.cpu_count()
        suggested_workers = min(available_cores-5, len(repositories))  
        max_workers = suggested_workers
        logger.info(f"Increasing worker threads to {max_workers} for better parallelism")
    
    # Process repositories in parallel using ProcessPoolExecutor for true parallelism
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_repo = {
            executor.submit(extract_dependencies, repo, output_dir, args, repo_req_data): repo
            for repo in tqdm(repositories, desc="Extracting dependencies", total=len(repositories))
        }
        
        # Process results as they complete with a detailed progress bar
        with tqdm(total=len(repositories), desc="Extracting dependencies", 
                 bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]") as pbar:
            for future in concurrent.futures.as_completed(future_to_repo):
                repo = future_to_repo[future]
                try:
                    repo_id, packages = future.result()
                    dependencies_by_repo.append(packages)
                    if repo_id:
                        # Display what we found for this repository
                        repo_name = repo_id.split('@')[0] if '@' in repo_id else repo_id
                        pbar.set_postfix_str(f"Found {len(packages)} packages in {repo_name}")
                except Exception as e:
                    # Handle error message formatting for both tuple and Path objects
                    if isinstance(repo, tuple):
                        repo_str = f"{repo[0]}@{repo[1]}"
                    else:
                        repo_str = str(repo)
                    logger.error(f"Error processing {repo_str}: {str(e)}")
                
                pbar.update(1)
    
    # Convert manager dict to regular dict
    repo_req_data_dict = dict(repo_req_data)
    
    # Merge all dependencies
    all_dependencies = set()
    for packages in dependencies_by_repo:
        all_dependencies.update(packages)
    
    # Save repo requirements to file
    repo_req_path = output_dir / "repo_req.json"
    logger.info(f"Saving repository requirements to {repo_req_path}")
    with open(repo_req_path, 'w') as f:
        json.dump(repo_req_data_dict, f, indent=2)
    
    # Save all dependencies to requirements.txt
    requirements_path = output_dir / "requirements.txt"
    logger.info(f"Saving unified requirements to {requirements_path}")
    with open(requirements_path, 'w') as f:
        for dep in sorted(all_dependencies):
            f.write(f"{dep}\n")
    
    # Print summary of findings
    logger.info(f"✨ Dependency analysis complete!")
    logger.info(f"📊 Summary:")
    logger.info(f"  - Found {len(all_dependencies)} unique dependencies across all repositories")
    logger.info(f"  - All repositories have at least 1 dependency: {all(len(deps) > 0 for deps in repo_req_data_dict.values())}")
    
    # Find most common dependencies (top 5)
    dep_counts = {}
    for deps in repo_req_data_dict.values():
        for dep in deps:
            dep_counts[dep] = dep_counts.get(dep, 0) + 1
    
    top_deps = sorted(dep_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    logger.info(f"  - Top dependencies:")
    for dep, count in top_deps:
        logger.info(f"    • {dep}: used in {count} repositories ({count/len(repositories):.1%})")
    
    logger.info(f"📄 Requirements saved to {requirements_path}")
    logger.info(f"📄 Repository requirements saved to {repo_req_path}")
    
    return all_dependencies, repo_req_data_dict


def create_unified_environment(all_dependencies, output_dir, args):
    """
    Create a unified virtual environment with all dependencies.
    
    Args:
        all_dependencies: Set of all dependencies
        output_dir: Output directory
        args: Command line arguments
    
    Returns:
        tuple: (venv_path, install_status)
    """
    logger = logging.getLogger(__name__)
    logger.info(f"🔧 Creating unified virtual environment with {len(all_dependencies)} dependencies")
    
    # Create virtual environment in the output directory
    venv_path = output_dir / "unified_venv"
    
    # Remove existing venv if it exists and overwrite is enabled
    if venv_path.exists() and args.overwrite:
        logger.info(f"Removing existing virtual environment at {venv_path}")
        shutil.rmtree(venv_path)
    
    if not venv_path.exists():
        if args.use_uv:
            logger.info(f"Creating virtual environment with UV at {venv_path}")
            try:
                result = subprocess.run(
                    ['uv', 'venv', str(venv_path)],
                    check=True,
                    capture_output=True,
                    text=True
                )
                logger.info(f"Virtual environment created successfully with UV")
            except Exception as e:
                logger.error(f"Failed to create virtual environment with UV: {str(e)}")
                return None, {}
        else:
            logger.info(f"Creating virtual environment with venv at {venv_path}")
            try:
                import venv
                venv.create(venv_path, with_pip=True)
                logger.info(f"Virtual environment created successfully with venv")
            except Exception as e:
                logger.error(f"Failed to create virtual environment with venv: {str(e)}")
                return None, {}
    else:
        logger.info(f"Using existing virtual environment at {venv_path}")
    
    # Install dependencies
    install_status = {}
    dependencies_list = sorted(all_dependencies)
    
    logger.info(f"🔄 Installing {len(dependencies_list)} dependencies...")
    
    # Group dependencies in batches of 10 for better progress visibility
    batch_size = min(10, len(dependencies_list))
    batches = [dependencies_list[i:i + batch_size] for i in range(0, len(dependencies_list), batch_size)]
    
    # Use a detailed progress bar for installation
    with tqdm(total=len(dependencies_list), desc="Installing dependencies", 
             bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]") as pbar:
        
        for batch_idx, batch in enumerate(batches, 1):
            logger.info(f"Processing batch {batch_idx}/{len(batches)} ({len(batch)} dependencies)")
            
            for dep in batch:
                try:
                    pbar.set_postfix_str(f"Installing {dep}")
                    
                    if args.use_uv:
                        # Use UV to install the dependency
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
                    else:
                        if args.verbose:
                            logger.info(f"Successfully installed {dep}")
                
                except Exception as e:
                    logger.error(f"Error installing {dep}: {str(e)}")
                    install_status[dep] = {
                        "success": False,
                        "error": str(e)
                    }
                
                pbar.update(1)
    
    # Save installation status to file
    install_status_path = output_dir / "install_status.json"
    logger.info(f"Saving installation status to {install_status_path}")
    with open(install_status_path, 'w') as f:
        json.dump(install_status, f, indent=2)
    
    # Count successful installations
    success_count = sum(1 for status in install_status.values() if status["success"])
    failure_count = len(all_dependencies) - success_count
    success_percent = (success_count / len(all_dependencies)) * 100 if all_dependencies else 0
    
    # Print installation summary
    logger.info(f"✨ Dependency installation complete!")
    logger.info(f"📊 Summary:")
    logger.info(f"  - Successfully installed {success_count} out of {len(all_dependencies)} dependencies ({success_percent:.1f}%)")
    
    if failure_count > 0:
        logger.warning(f"  - {failure_count} dependencies failed to install")
        # List the first few failed dependencies
        failed_deps = [dep for dep, status in install_status.items() if not status["success"]]
        for i, dep in enumerate(failed_deps[:5]):
            logger.warning(f"    • {dep}: {install_status[dep]['error'][:100]}")
        if len(failed_deps) > 5:
            logger.warning(f"    • ... and {len(failed_deps) - 5} more")
    
    logger.info(f"📄 Installation status saved to {install_status_path}")
    
    return venv_path, install_status


def run_tests_for_repo(repo_info, output_dir, unified_venv, args):
    """
    Run tests for a single repository using the unified virtual environment.
    
    Args:
        repo_info: Repository information (tuple or Path)
        output_dir: Output directory
        unified_venv: Path to the unified virtual environment
        args: Command line arguments
    
    Returns:
        dict: Test results
    """
    # Configure logging for process
    logger = logging.getLogger(__name__)
    
    # Initialize repository manager
    repo_manager = RepoManager(output_dir=output_dir, logger=logger)
    
    result_data = {
        "repository": None,
        "status": "running",
        "execution": {
            "start_time": time.time(),
            "elapsed_time": 0
        },
        "tests": {
            "found": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "details": []
        },
        "logs": []
    }
    
    def add_log_entry(message, level="INFO", **kwargs):
        """Add a log entry to both the logger and result data."""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = {
            "timestamp": timestamp,
            "level": level,
            "message": message,
            **kwargs
        }
        result_data["logs"].append(log_entry)
        
        if level == "INFO":
            logger.info(message)
        elif level == "WARNING":
            logger.warning(message)
        elif level == "ERROR":
            logger.error(message)
    
    try:
        # Clone or set up local repository
        if isinstance(repo_info, tuple):
            full_name, sha = repo_info
            working_dir = repo_manager.clone_repository(full_name, sha)
            repo_id = f"{full_name}@{sha}"
        else:
            local_path = Path(repo_info) if not isinstance(repo_info, Path) else repo_info
            # Use the repository directly without copying
            working_dir = repo_manager.use_local_repository(local_path)
            repo_id = str(local_path.resolve())
        
        result_data["repository"] = repo_id
        add_log_entry(f"Processing repository: {repo_id}")
        
        # Install the package in development mode
        try:
            if sys.platform == 'win32':
                pip_path = unified_venv / 'Scripts' / 'pip.exe'
            else:
                pip_path = unified_venv / 'bin' / 'pip'
            
            add_log_entry("Installing Cython")
            result = subprocess.run(
                [str(pip_path), 'install', 'Cython'],
                check=True,
                capture_output=True,
                text=True
            )
            
            add_log_entry("Installing package in development mode (pip install -e .)")
            result = subprocess.run(
                [str(pip_path), 'install', '-e', '.'],
                cwd=working_dir,
                check=True,
                capture_output=True,
                text=True
            )
            add_log_entry(f"Successfully installed package in development mode")
        except Exception as e:
            add_log_entry(f"Failed to install package in development mode: {str(e)}", level="WARNING")
        
        # Run tests
        test_runner = TestRunner(working_dir, venv_path=unified_venv, use_uv=args.use_uv, 
                               logger=logger, timeout=args.timeout)
        
        add_log_entry("Looking for tests in the repository")
        test_files = test_runner.find_tests()
        
        if not test_files:
            add_log_entry("No tests found. Marking repository as 'skip'")
            result_data["status"] = "skip"
            return result_data
        
        add_log_entry(f"Found {len(test_files)} test files")
        
        # Run tests
        test_results = test_runner.run_tests()
        
        # Parse test results
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
            add_log_entry("No test cases found. Marking repository as 'skip'")
        elif failure_count > 0:
            if success_count > 0:
                result_data["status"] = "partial_success"
                add_log_entry(f"Some tests passed ({success_count}), some failed ({failure_count}). Marking as 'partial_success'")
            else:
                result_data["status"] = "failure"
                add_log_entry(f"All tests failed ({failure_count}). Marking as 'failure'")
        else:
            result_data["status"] = "success"
            add_log_entry(f"All tests passed ({success_count}). Marking as 'success'")
        
        # Update execution time
        end_time = time.time()
        result_data["execution"]["elapsed_time"] = end_time - result_data["execution"]["start_time"]
        
        return result_data
    
    except Exception as e:
        add_log_entry(f"Error running tests: {str(e)}", level="ERROR")
        result_data["status"] = "error"
        result_data["error"] = str(e)
        
        # Update execution time
        end_time = time.time()
        result_data["execution"]["elapsed_time"] = end_time - result_data["execution"]["start_time"]
        
        return result_data


def run_tests_parallel(repositories, output_dir, unified_venv, args):
    """
    Run tests for all repositories in parallel.
    
    Args:
        repositories: List of repositories
        output_dir: Output directory
        unified_venv: Path to the unified virtual environment
        args: Command line arguments
    
    Returns:
        dict: Test results by repository
    """
    logger = logging.getLogger(__name__)
    logger.info(f"🧪 Running tests for {len(repositories)} repositories using unified environment")
    
    # Print environment info
    logger.info(f"📂 Environment details:")
    logger.info(f"  - Virtual environment: {unified_venv}")
    
    # Try to get Python version in the virtual environment
    try:
        if sys.platform == 'win32':
            python_path = unified_venv / 'Scripts' / 'python.exe'
        else:
            python_path = unified_venv / 'bin' / 'python'
        
        result = subprocess.run(
            [str(python_path), '--version'],
            check=True,
            capture_output=True,
            text=True
        )
        logger.info(f"  - Python version: {result.stdout.strip()}")
    except Exception:
        logger.info(f"  - Python version: Unknown")
    
    # Results file
    records_path = output_dir / "records.jsonl"
    logger.info(f"📄 Test results will be saved to {records_path}")
    
    # Clear existing records.jsonl if it exists
    if records_path.exists():
        with open(records_path, 'w') as f:
            # Empty the file
            pass
    
    # Increase default max_workers for better parallelism
    max_workers = args.max_workers
    if max_workers <= 4 and len(repositories) > 10:
        # Use more workers for larger numbers of repositories
        # but don't exceed available CPU cores
        import multiprocessing
        available_cores = multiprocessing.cpu_count()
        suggested_workers = min(available_cores, len(repositories), 16)  
        max_workers = suggested_workers
        logger.info(f"Increasing worker threads to {max_workers} for better parallelism")
    
    # Process repositories in parallel
    all_results = []
    
    # Use a thread pool for the test running
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_repo = {
            executor.submit(run_tests_for_repo, repo, output_dir, unified_venv, args): repo
            for repo in repositories
        }
        
        # Process results as they complete with a detailed progress bar
        total_tests = 0
        passed_tests = 0
        failed_tests = 0
        skipped_tests = 0
        
        # Create a progress bar with more information
        with tqdm(total=len(repositories), desc="Running tests", 
                 bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]") as pbar:
            for future in concurrent.futures.as_completed(future_to_repo):
                repo = future_to_repo[future]
                try:
                    # Display which repository is currently being processed
                    repo_name = ""
                    if isinstance(repo, tuple):
                        repo_name = repo[0]  # GitHub repo name
                    else:
                        # For Path objects or string paths
                        path_obj = Path(repo) if not isinstance(repo, Path) else repo
                        repo_name = path_obj.name  # Local directory name
                    
                    pbar.set_postfix_str(f"Processing {repo_name}")
                    result = future.result()
                    all_results.append(result)
                    
                    # Update test statistics
                    repo_tests = result.get("tests", {})
                    total_tests += repo_tests.get("found", 0)
                    passed_tests += repo_tests.get("passed", 0)
                    failed_tests += repo_tests.get("failed", 0)
                    skipped_tests += repo_tests.get("skipped", 0)
                    
                    # Update status in progress bar
                    status = result.get("status", "unknown")
                    pbar.set_postfix_str(f"{repo_name}: {status}")
                    
                    # Append to records.jsonl
                    with open(records_path, 'a') as f:
                        f.write(json.dumps(result) + '\n')
                    
                except Exception as e:
                    # Handle error message formatting for both tuple and Path objects
                    if isinstance(repo, tuple):
                        repo_str = f"{repo[0]}@{repo[1]}"
                    else:
                        repo_str = str(repo)
                    logger.error(f"Error processing {repo_str}: {str(e)}")
                
                pbar.update(1)
    
    # Count repositories by status
    status_counts = {
        "success": 0,
        "partial_success": 0,
        "failure": 0,
        "skip": 0,
        "error": 0
    }
    
    for result in all_results:
        status = result.get("status", "error")
        if status in status_counts:
            status_counts[status] += 1
    
    # Print test summary with emojis for better readability
    logger.info(f"✨ Test execution complete!")
    logger.info(f"📊 Repository status summary:")
    logger.info(f"  ✅ Success: {status_counts['success']} repositories")
    logger.info(f"  ⚠️ Partial success: {status_counts['partial_success']} repositories")
    logger.info(f"  ❌ Failure: {status_counts['failure']} repositories")
    logger.info(f"  ⏩ Skip (no tests): {status_counts['skip']} repositories")
    logger.info(f"  🔥 Error: {status_counts['error']} repositories")
    
    # Calculate percentages safely
    passed_percent = (passed_tests / total_tests * 100) if total_tests > 0 else 0
    failed_percent = (failed_tests / total_tests * 100) if total_tests > 0 else 0
    skipped_percent = (skipped_tests / total_tests * 100) if total_tests > 0 else 0
    
    logger.info(f"📊 Test case summary:")
    logger.info(f"  - Total test cases: {total_tests}")
    logger.info(f"  - Passed: {passed_tests} ({passed_percent:.1f}%)")
    logger.info(f"  - Failed: {failed_tests} ({failed_percent:.1f}%)")
    logger.info(f"  - Skipped: {skipped_tests} ({skipped_percent:.1f}%)")
    
    return all_results


def filter_successful_repos(test_results):
    """
    Filter repositories that pass all tests or have no tests.
    
    Args:
        test_results: List of test results
    
    Returns:
        list: List of repository IDs that pass all tests or have no tests
    """
    successful_repos = []
    
    for result in test_results:
        status = result.get("status", "")
        repo_id = result.get("repository", "")
        
        if status == "success" or status == "skip":
            successful_repos.append(repo_id)
    
    return successful_repos


def main():
    """Main entry point for the application."""
    start_time = time.time()
    
    # Parse arguments
    args = parse_arguments()
    
    # Configure logging
    logger = configure_process_logging(args.verbose)
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Using output directory: {output_dir}")
    
    try:
        # Print banner
        logger.info("=" * 80)
        logger.info(f"🚀 Starting Repo2Run Unified Pipeline")
        logger.info(f"📅 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 80)
        
        # Load repositories
        logger.info("\n" + "=" * 40)
        logger.info("📋 STAGE 1: LOADING REPOSITORIES")
        logger.info("=" * 40)
        repositories = load_repositories(args)
        if not repositories:
            logger.error("No repositories to process. Exiting.")
            return 1
        
        # Stage 1: Analyze dependencies across all repositories
        logger.info("\n" + "=" * 40)
        logger.info("🔍 STAGE 2: ANALYZING DEPENDENCIES")
        logger.info("=" * 40)
        all_dependencies, repo_req_data = analyze_dependencies_parallel(repositories, output_dir, args)
        
        # Stage 2: Create unified virtual environment with all dependencies
        logger.info("\n" + "=" * 40)
        logger.info("🏗️ STAGE 3: CREATING UNIFIED ENVIRONMENT")
        logger.info("=" * 40)
        unified_venv, install_status = create_unified_environment(all_dependencies, output_dir, args)
        if not unified_venv:
            logger.error("Failed to create unified virtual environment. Exiting.")
            return 1
        
        # Stage 3: Run tests for each repository
        logger.info("\n" + "=" * 40)
        logger.info("🧪 STAGE 4: RUNNING TESTS")
        logger.info("=" * 40)
        test_results = run_tests_parallel(repositories, output_dir, unified_venv, args)
        
        # Stage 4: Filter repositories that pass all tests or have no tests
        logger.info("\n" + "=" * 40)
        logger.info("🎯 STAGE 5: FILTERING SUCCESSFUL REPOSITORIES")
        logger.info("=" * 40)
        successful_repos = filter_successful_repos(test_results)
        
        # Save the list of successful repositories
        successful_repos_path = output_dir / "successful_repos.json"
        with open(successful_repos_path, 'w') as f:
            json.dump(successful_repos, f, indent=2)
        
        logger.info(f"Found {len(successful_repos)} repositories that pass all tests or have no tests")
        logger.info(f"Successful repositories saved to {successful_repos_path}")
        
        # Print success rate
        success_rate = len(successful_repos) / len(repositories) * 100 if repositories else 0
        logger.info(f"Success rate: {success_rate:.1f}% ({len(successful_repos)}/{len(repositories)})")
        
        # Print summary of files generated
        logger.info("\n" + "=" * 40)
        logger.info("📊 SUMMARY OF GENERATED FILES")
        logger.info("=" * 40)
        logger.info(f"1. requirements.txt: Union of all dependencies (without versions)")
        logger.info(f"2. repo_req.json: Mapping of repositories to dependencies")
        logger.info(f"3. install_status.json: Installation status for each dependency")
        logger.info(f"4. records.jsonl: Detailed test results for each repository")
        logger.info(f"5. successful_repos.json: List of repositories that pass all tests or have no tests")
        
        # Print total execution time
        end_time = time.time()
        execution_time = end_time - start_time
        hours, remainder = divmod(execution_time, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        logger.info("\n" + "=" * 80)
        logger.info(f"✨ Unified Pipeline completed successfully in {int(hours)}h {int(minutes)}m {int(seconds)}s")
        logger.info("=" * 80)
        
        return 0
    
    except Exception as e:
        logger.error(f"Error in main execution: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main()) 