#!/usr/bin/env python3
# Copyright (c) 2023-2024 Repo2Run Contributors

"""
Main entry point for Repo2Run.
This script handles the workflow of:
1. Cloning or using a local repository
2. Extracting and unifying requirements
3. Installing dependencies using UV or pip
4. Running tests

Usage:
    # Single repository/directory mode:
    repo2run --repo user/repo sha --output-dir output_path [--overwrite] [--verbose] [--skip-processed]
    repo2run --local path/to/repo --output-dir output_path [--overwrite] [--verbose] [--skip-processed]

    # Multiprocessing mode:
    repo2run --repo-list repos.txt --output-dir output_path [--overwrite] [--verbose] [--num-workers N] [--skip-processed]
    repo2run --local-list dirs.txt --output-dir output_path [--overwrite] [--verbose] [--num-workers N] [--skip-processed]
    
    # Global unified pipeline mode (complete):
    repo2run --global --repo-list repos.txt --output-dir output_path [--overwrite] [--verbose] [--max-workers N] [--repo-range START END]
    repo2run --global --local-list dirs.txt --output-dir output_path [--overwrite] [--verbose] [--max-workers N] [--repo-range START END]
    
    # Global unified pipeline mode (separate stages):
    repo2run --global --repo-list repos.txt --output-dir output_path --extract-dep
    repo2run --global --repo-list repos.txt --output-dir output_path --config-venv
    repo2run --global --repo-list repos.txt --output-dir output_path --run-test
    
    # Test extraction mode:
    repo2run --repo user/repo sha --output-dir output_path --extract-tests
    repo2run --local path/to/repo --output-dir output_path --extract-tests
    repo2run --repo-list repos.txt --output-dir output_path --extract-tests [--num-workers N]
    repo2run --local-list dirs.txt --output-dir output_path --extract-tests [--num-workers N]
    # Note: --extract-tests uses direct repository access, doesn't copy to output folder, 
    # and doesn't generate results.jsonl (only test.jsonl)

    # Run tests from previously extracted tests:
    repo2run --output-dir output_path --run-tests [--num-workers N]
    # Note: --run-tests reads tests.jsonl from the output directory, recreates the test files in 
    # temporary folders, and runs them directly with the system Python interpreter without creating
    # virtual environments or installing dependencies. Results are written to test_results.jsonl.

Options:
    --repo FULL_NAME SHA    The full name of the repository (e.g., user/repo) and SHA
    --local PATH            Local folder path to process
    --repo-list FILE       Text file containing list of repositories (format: user/repo sha)
    --local-list FILE      Text file containing list of local directories
    --run-tests           Run tests from previously extracted test.jsonl file directly with the system Python, skipping dependency installation and venv configuration
    --global               Use the unified global pipeline (single environment for all repositories)
    --output-dir DIR       Directory to store output files (default: output)
    --workspace-dir DIR    Directory to use as workspace (default: temporary directory)
    --timeout SECONDS      Timeout in seconds (default: 1800 - 0.5 hours). Tests that exceed this time will be forcibly terminated.
    --verbose             Enable verbose logging
    --overwrite           Overwrite existing output directory if it exists
    --use-uv             Use UV for dependency management (default: False, use pip/venv)
    --num-workers N       Number of worker processes for parallel processing (default: number of CPU cores)
    --max-workers N       Number of worker threads for parallel processing in global mode (default: 4)
    --repo-range START END Process only a range of repositories (e.g., 0 100 for repos 0-99). Zero-indexed. Only applies in global mode.
    --collect-only      Only collect test cases without installing dependencies or running tests
    --skip-processed    Skip repositories that have already been processed (default: False)
    --extract-dep       Only extract dependencies from repositories (Stage 1 of global pipeline)
    --config-venv       Only configure the virtual environment with extracted dependencies (Stage 2 of global pipeline)
    --run-test          Only run tests using the configured virtual environment (Stage 3 of global pipeline)
    --extract-tests     Extract test files from repositories and write them to test.jsonl (repositories will not be copied to output folder and results.jsonl will not be generated)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import datetime
import multiprocessing
import logging
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Set, Any
from tqdm import tqdm
import re
import threading
import tempfile
import glob
import concurrent.futures
import ast
import traceback

from repo2run.utils.repo_manager import RepoManager
from repo2run.utils.dependency_extractor import DependencyExtractor
from repo2run.utils.dependency_installer import DependencyInstaller
from repo2run.utils.test_runner import TestRunner
from repo2run.utils.logger import configure_process_logging
from repo2run.unified_pipeline import (
    load_repositories,
    analyze_dependencies_parallel,
    create_unified_environment,
    run_tests_parallel,
    filter_successful_repos,
    build_dependencies_from_jsonl
)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Configure and run repositories with automated dependency management.'
    )
    
    # Create mutually exclusive group for repo source
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        '--repo', 
        nargs=2, 
        metavar=('FULL_NAME', 'SHA'),
        help='The full name of the repository (e.g., user/repo) and SHA'
    )
    source_group.add_argument(
        '--local', 
        type=str, 
        metavar='PATH',
        help='Local folder path to process'
    )
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
    source_group.add_argument(
        '--run-tests',
        action='store_true',
        help='Run tests from previously extracted test.jsonl file directly with the system Python, skipping dependency installation and venv configuration'
    )
    
    # Global mode flag
    parser.add_argument(
        '--global',
        dest='global_mode',
        action='store_true',
        help='Use the unified global pipeline (single environment for all repositories)'
    )
    
    # Pipeline stage flags - for global mode
    pipeline_group = parser.add_argument_group('Pipeline Stages (for --global mode)')
    pipeline_group.add_argument(
        '--extract-dep',
        action='store_true',
        help='Only extract dependencies from repositories (Stage 1)'
    )
    pipeline_group.add_argument(
        '--config-venv',
        action='store_true',
        help='Only configure the virtual environment with extracted dependencies (Stage 2)'
    )
    pipeline_group.add_argument(
        '--run-test',
        action='store_true',
        help='Only run tests using the configured virtual environment (Stage 3)'
    )
    
    # Test extraction flag
    parser.add_argument(
        '--extract-tests',
        action='store_true',
        help='Extract test files from repositories and write them to test.jsonl (repositories will not be copied to output folder and results.jsonl will not be generated)'
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
        default=1800,
        help='Timeout in seconds (default: 1800 - 0.5 houra). Tests that exceed this time will be forcibly terminated.'
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
        '--num-workers',
        type=int,
        default=multiprocessing.cpu_count(),
        help='Number of worker processes for parallel processing (default: number of CPU cores)'
    )
    parser.add_argument(
        '--max-workers',
        type=int,
        default=4,
        help='Number of worker threads for parallel processing in global mode (default: 4)'
    )
    parser.add_argument(
        '--repo-range',
        type=int,
        nargs=2,
        metavar=('START', 'END'),
        help='Process only a range of repositories (e.g., 0 100 for repos 0-99). Zero-indexed. Only applies in global mode.'
    )
    parser.add_argument(
        '--collect-only',
        action='store_true',
        help='Only collect test cases without installing dependencies or running tests'
    )
    parser.add_argument(
        '--skip-processed',
        action='store_true',
        help='Skip repositories that have already been processed (default: False)'
    )
    
    parser.add_argument(
        '--help-install',
        action='store_true',
        help='Automatically attempt to install missing dependencies needed for tests (only used with --run-tests)'
    )
    
    parser.add_argument(
        '--require-tested-files',
        action='store_true',
        help='Skip running test files that do not have associated tested_files information (only used with --run-tests)'
    )
    
    return parser.parse_args()


def run_unified_pipeline(args):
    """
    Unified pipeline for processing repositories.
    
    This pipeline handles all stages:
    1. Extract dependencies from repositories
    2. Configure a unified virtual environment
    3. Run tests using the unified environment
    
    Args:
        args: Command line arguments
    
    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
    # Configure logging for the main process
    logger = configure_process_logging(args.verbose)
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load repositories from repo-list or local-list
    if args.repo_list:
        repositories = load_repositories(args)
    elif args.local_list:
        repositories = load_repositories(args)
    else:
        logger.error("No repository list or local directory list provided")
        return 1
    
    # Check if we found any repositories to process
    if not repositories:
        logger.info("No repositories to process")
        return 0
        
    # Check if we should extract tests - handled separately from regular pipeline
    if args.extract_tests:
        logger.info("\n" + "=" * 40)
        logger.info("🔍 EXTRACTING TEST FILES")
        logger.info("=" * 40)
        
        # Initialize test.jsonl file
        tests_jsonl_path = output_dir / "test.jsonl"
        
        # Always overwrite test.jsonl for extract-tests
        if tests_jsonl_path.exists():
            logger.info(f"Overwriting existing test file at {tests_jsonl_path}")
            tests_jsonl_path.unlink()
        
        # Process repositories in parallel
        def extract_tests_for_repo(repo_info):
            try:
                # Determine repo identifier
                if isinstance(repo_info, tuple):
                    # GitHub repository
                    full_name, sha = repo_info
                    repo_identifier = f"{full_name}@{sha}"
                    
                    # Clone the repository to a temporary directory
                    temp_dir = tempfile.mkdtemp(prefix="repo2run_")
                    try:
                        repo_path = Path(temp_dir)
                        logger.info(f"Cloning repository {full_name}@{sha} to {repo_path}")
                        
                        # Clone the repository
                        repo_manager = RepoManager(output_dir=None, logger=logger)
                        repo_manager.clone_repository(full_name, sha, repo_path)
                        
                        # Extract test files
                        tests_data = extract_test_files(repo_path, repo_identifier, True)
                        
                        # Clean up temporary directory
                        logger.info(f"Cleaning up temporary directory {temp_dir}")
                        shutil.rmtree(temp_dir)
                        
                        # Skip repositories with no valid test files
                        if not tests_data:
                            logger.info(f"No valid test files found in repository {repo_identifier} (skipping)")
                            return None
                        
                        # Return the data to be written to test.jsonl
                        return {
                            "repository": repo_identifier,
                            "tests": tests_data
                        }
                    except Exception as e:
                        logger.error(f"Error processing repository {repo_identifier}: {e}")
                        # Clean up temporary directory if it exists
                        if os.path.exists(temp_dir):
                            shutil.rmtree(temp_dir)
                        return None
                else:  # Local directory
                    repo_path = Path(repo_info)
                    repo_identifier = str(repo_path.absolute())
                    
                    # Use the local repository directly
                    logger.info(f"Using direct access to local repository at {repo_path}")
                    
                    # Extract test files (not a temp dir, so no need to clean up)
                    tests_data = extract_test_files(repo_path, repo_identifier, False)
                    
                    # Skip repositories with no valid test files
                    if not tests_data:
                        logger.info(f"No valid test files found in repository {repo_identifier} (skipping)")
                        return None
                    
                    # Return the data to be written to test.jsonl
                    return {
                        "repository": repo_identifier,
                        "tests": tests_data
                    }
            except Exception as e:
                logger.error(f"Error extracting tests for {repo_info}: {e}")
                return None
        
        # Process repositories in parallel with progress bar
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            futures = [executor.submit(extract_tests_for_repo, repo) for repo in repositories]
            
            # Process results as they complete
            for future in tqdm(concurrent.futures.as_completed(futures), 
                               total=len(futures), 
                               desc="Extracting tests from repositories"):
                result = future.result()
                if result:
                    results.append(result)
        
        # Save results to test.jsonl
        logger.info(f"Writing {len(results)} test records to {tests_jsonl_path}")
        with open(tests_jsonl_path, 'w') as f:
            for record in results:
                f.write(json.dumps(record) + '\n')
        
        logger.info(f"Test extraction completed. Test data written to {tests_jsonl_path}")
        return 0
    
    # Check if we should run a complete pipeline or just specific stages
    run_complete_pipeline = not (args.extract_dep or args.config_venv or args.run_test)
    
    # Complete pipeline or specific stages (other than just running tests)
    unified_venv = None
    
    # Step 1: Extract dependencies from all repositories
    if args.extract_dep or run_complete_pipeline:
        logger.info("\n" + "=" * 40)
        logger.info("📦 STAGE 1: ANALYZING DEPENDENCIES")
        logger.info("=" * 40)
        all_dependencies, repo_req_data = analyze_dependencies_parallel(repositories, output_dir, args)
        
        # Save all dependencies to a requirements.txt file
        requirements_path = output_dir / "requirements.txt"
        with open(requirements_path, 'w') as f:
            for dependency in sorted(all_dependencies):
                f.write(f"{dependency}\n")
        
        logger.info(f"Found {len(all_dependencies)} unique dependencies across all repositories")
        logger.info(f"Dependencies saved to {requirements_path}")
    
    # Step 2: Configure a unified virtual environment for all repositories
    if args.config_venv or run_complete_pipeline:
        logger.info("\n" + "=" * 40)
        logger.info("🔧 STAGE 2: CONFIGURING VIRTUAL ENVIRONMENT")
        logger.info("=" * 40)
        
        # Check if dependencies file exists
        requirements_path = output_dir / "requirements.txt"
        if not requirements_path.exists():
            if args.extract_dep:
                logger.error(f"Requirements file not found at {requirements_path}. Run with --extract-dep first.")
                return 1
            else:
                # Try to read dependencies from repo_req.jsonl
                logger.info("requirements.txt not found, attempting to build it from repo_req.jsonl...")
                try:
                    dependencies = build_dependencies_from_jsonl(output_dir)
                    # Save all dependencies to a requirements.txt file
                    with open(requirements_path, 'w') as f:
                        for dependency in sorted(dependencies):
                            f.write(f"{dependency}\n")
                    
                    logger.info(f"Found {len(dependencies)} unique dependencies from repo_req.jsonl")
                    logger.info(f"Dependencies saved to {requirements_path}")
                except Exception as e:
                    logger.error(f"Failed to build requirements.txt: {e}")
                    return 1
        
        # Create virtual environment
        unified_venv = create_unified_environment(requirements_path, output_dir, args.use_uv, logger)
        if not unified_venv:
            logger.error("Failed to create unified virtual environment")
            return 1
        
        # Save the path to the unified virtual environment
        venv_path_file = output_dir / "venv_path.txt"
        with open(venv_path_file, 'w') as f:
            f.write(str(unified_venv))
        
        logger.info(f"Virtual environment path saved to {venv_path_file}")
    elif run_complete_pipeline:
        # If running complete pipeline, check if venv_path.txt exists
        venv_path_file = output_dir / "venv_path.txt"
        if not venv_path_file.exists():
            logger.error(f"Virtual environment path file not found at {venv_path_file}. Run with --config-venv first.")
            return 1
        
        try:
            with open(venv_path_file, 'r') as f:
                unified_venv = Path(f.read().strip())
            if not unified_venv.exists():
                logger.error(f"Virtual environment not found at {unified_venv}.")
                return 1
            logger.info(f"Using existing virtual environment at {unified_venv}")
        except Exception as e:
            logger.error(f"Failed to load virtual environment path: {e}")
            return 1
    
    # Step 3: Run tests for each repository
    if args.run_test or run_complete_pipeline:
        logger.info("\n" + "=" * 40)
        logger.info("🧪 STAGE 3: RUNNING TESTS")
        logger.info("=" * 40)
        test_results = run_tests_parallel(repositories, output_dir, unified_venv, args)
        
        # Step 4: Filter repositories that pass all tests or have no tests
        logger.info("\n" + "=" * 40)
        logger.info("🎯 STAGE 4: FILTERING SUCCESSFUL REPOSITORIES")
        logger.info("=" * 40)
        successful_repos = filter_successful_repos(test_results)
        
        # Save the list of successful repositories
        successful_repos_path = output_dir / "successful_repos.json"
        with open(successful_repos_path, 'w') as f:
            json.dump(successful_repos, f, indent=2)
        
        logger.info(f"Found {len(successful_repos)} repositories that pass all tests or have no tests")
        logger.info(f"Successful repositories saved to {successful_repos_path}")
    
    return 0


def has_repo_been_processed(results_jsonl_path: Path, repo_identifier: str) -> bool:
    """Check if the repository has already been processed by looking in results.jsonl.
    
    Args:
        results_jsonl_path: Path to the results.jsonl file
        repo_identifier: The unique identifier for the repository
    
    Returns:
        bool: True if the repository has been processed, False otherwise
    """
    if not results_jsonl_path.exists():
        return False
    
    try:
        with open(results_jsonl_path, 'r') as f:
            for line in f:
                try:
                    result = json.loads(line.strip())
                    # Check if this result matches our repo - repository field stores the path or GitHub repo@sha
                    if result.get("repository") == repo_identifier:
                        # Only consider it processed if it has a final status (not "running")
                        if result.get("status") != "running":
                            return True
                except json.JSONDecodeError:
                    # Skip invalid lines
                    continue
    except Exception:
        # If we can't read the file for any reason, assume the repo hasn't been processed
        return False
    
    return False


def get_processed_repos(results_jsonl_path: Path) -> Set[str]:
    """Get the set of repository identifiers that have already been processed.
    
    Args:
        results_jsonl_path: Path to the results.jsonl file
    
    Returns:
        Set of repository identifiers that have already been processed
    """
    processed_repos = set()
    try:
        with open(results_jsonl_path, 'r') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    result = json.loads(line)
                    # Only consider it processed if it has a final status (not "running")
                    if result.get("status") != "running" and "repository" in result:
                        processed_repos.add(result.get("repository"))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"Error reading results file: {e}")
    
    return processed_repos


def cleanup_temp_directories(logger=None):
    """
    Clean up temporary directories created by the application.
    
    This function removes:
    - Temporary directories created by Python's tempfile module
    - Specific temporary directories used by Repo2Run
    
    Args:
        logger (logging.Logger, optional): Logger for reporting cleanup actions
    """
    try:
        # Clean Python's default temporary directory
        default_temp_dir = tempfile.gettempdir()
        
        # Find and remove temporary directories
        temp_patterns = [
            os.path.join(default_temp_dir, 'repo2run_*'),  # Repo2Run specific temp dirs
            os.path.join(default_temp_dir, 'tmp*'),        # General temporary directories
            os.path.join(default_temp_dir, 'pip_*'),       # Pip cache directories
            os.path.join(default_temp_dir, 'uv_*')         # UV cache directories
        ]
        
        removed_dirs = 0
        for pattern in temp_patterns:
            for temp_dir in glob.glob(pattern):
                try:
                    # Check if it's a directory and not currently in use
                    if os.path.isdir(temp_dir):
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        removed_dirs += 1
                        if logger:
                            logger.info(f"Removed temporary directory: {temp_dir}")
                except Exception as e:
                    if logger:
                        logger.warning(f"Failed to remove temporary directory {temp_dir}: {e}")
        
        if logger:
            logger.info(f"Cleaned up {removed_dirs} temporary directories")
    except Exception as e:
        if logger:
            logger.warning(f"Error during temporary directory cleanup: {e}")


def cleanup_resources(working_dir: Path, venv_path: Path, logger=None):
    """Aggressively clean up resources to minimize storage consumption.
    
    Args:
        working_dir (Path): Directory of the processed repository
        venv_path (Path): Path to the virtual environment
        logger (logging.Logger, optional): Logger for reporting cleanup actions
    """
    try:
        # Remove virtual environment
        if venv_path and venv_path.exists():
            if logger:
                logger.info(f"Removing virtual environment at {venv_path}")
            shutil.rmtree(venv_path, ignore_errors=True)
        
        # Remove working directory
        if working_dir and working_dir.exists():
            if logger:
                logger.info(f"Removing working directory at {working_dir}")
            shutil.rmtree(working_dir, ignore_errors=True)
        
        # Additional cleanup: remove any pip or package caches
        try:
            subprocess.run([sys.executable, '-m', 'pip', 'cache', 'purge'], 
                           capture_output=True, text=True, check=False)
        except Exception:
            pass
        
        # Clean up temporary directories
        cleanup_temp_directories(logger)
    except Exception as e:
        if logger:
            logger.warning(f"Error during resource cleanup: {e}")


def process_single_repo(args: argparse.Namespace, repo_info: Optional[Tuple[str, str]] = None, local_path: Optional[str] = None) -> int:
    """Process a single repository or local directory.
    
    Args:
        args: Command line arguments
        repo_info: Tuple of (full_name, sha) for repository mode
        local_path: Path to local directory for local mode
    
    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
    start_time = time.time()
    temp_dir = None
    
    # Configure logging for this process
    logger = configure_process_logging(args.verbose)
    
    # Set up a global timeout to ensure this process doesn't exceed the timeout
    def timeout_handler():
        while True:
            elapsed_time = time.time() - start_time
            if elapsed_time > args.timeout:
                logger.error(f"Process exceeded timeout of {args.timeout} seconds")
                # Force exit this process with a more direct approach
                os._exit(1)
            time.sleep(1)  # Check more frequently (every 1 second)
    
    # Start the timeout handler in a separate thread
    timeout_thread = threading.Thread(target=timeout_handler, daemon=True)
    timeout_thread.start()
    
    # Create a timer that will terminate the process after the timeout
    # This is a backup mechanism in case the thread-based timeout fails
    def hard_timeout_handler():
        logger.error(f"Process hard timeout after {args.timeout} seconds")
        os._exit(1)
    
    timer = threading.Timer(args.timeout, hard_timeout_handler)
    timer.daemon = True
    timer.start()
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Ensure absolute path for output directory
    output_dir = output_dir.resolve()
    
    # Initialize results.jsonl file
    results_jsonl_path = output_dir / "results.jsonl"
    
    # Initialize test.jsonl file if extract-tests is enabled
    tests_jsonl_path = output_dir / "test.jsonl"
    
    # Pre-determine repo identifier for checking if it's already processed
    repo_identifier = None
    if repo_info:
        full_name, sha = repo_info
        repo_identifier = f"{full_name}@{sha}"
    elif local_path:
        local_path_resolved = Path(local_path)
        repo_identifier = str(local_path_resolved)
    
    # Initialize result data structure with temporary values - will update repository later
    result_data = {
        "repository": repo_identifier if repo_identifier else "pending",  # Set repository identifier immediately if we have it
        "status": "running",
        "configuration": {
            "output_directory": str(output_dir),
            "overwrite_mode": args.overwrite,
            "timeout": args.timeout,
            "use_uv": args.use_uv
        },
        "dependencies": {
            "found": 0,
            "installed": 0,
            "details": []
        },
        "tests": {
            "found": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "details": []
        },
        "execution": {
            "start_time": start_time,
            "elapsed_time": 0
        },
    }
    
    def add_log_entry(message: str, level: str = "INFO", **kwargs):
        """Add a log entry to the logger only."""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if level == "INFO":
            logger.info(message)
        elif level == "WARNING":
            logger.warning(message)
        elif level == "ERROR":
            logger.error(message)
    
    try:
        # Initialize repository directly in output directory
        repo_manager = RepoManager(output_dir=output_dir, logger=logger)
        
        # Now that we have repo_manager, determine the repository identifier
        if repo_info:
            full_name, sha = repo_info
            # If extract-tests flag is enabled, use direct access to avoid copying
            if args.extract_tests:
                # First clone to a temporary directory
                temp_dir = tempfile.mkdtemp(prefix="repo2run_")
                add_log_entry(f"Created temporary directory for cloning: {temp_dir}")
                
                # Clone directly to temp directory
                try:
                    # Clone repository
                    clone_cmd = ['git', 'clone', f'https://github.com/{full_name}.git', 
                                '--quiet', '--depth=1', '--branch', sha if sha.startswith('v') else '', temp_dir]
                    if not sha.startswith('v'):
                        # For non-tag SHAs, remove --branch option
                        clone_cmd.pop(-2)
                        clone_cmd.pop(-2)
                    
                    subprocess.run(clone_cmd, check=True, capture_output=True)
                    
                    if not sha.startswith('v'):
                        # For non-tag SHAs, checkout the specific commit
                        checkout_cmd = ['git', 'checkout', sha, '--quiet']
                        subprocess.run(checkout_cmd, cwd=temp_dir, check=True, capture_output=True)
                    
                    # Use the temporary directory directly
                    working_dir = Path(temp_dir)
                    add_log_entry(f"Using direct access to cloned repository at {working_dir}")
                except Exception as e:
                    add_log_entry(f"Failed to clone directly: {e}. Falling back to standard approach.", level="WARNING")
                    # Fall back to standard approach
                    working_dir = repo_manager.clone_repository(full_name, sha)
            else:
                # Standard approach for non-extract-tests mode
                working_dir = repo_manager.clone_repository(full_name, sha)
                
            repo_name = working_dir.name
            add_log_entry(f"Cloned repository {full_name} at {sha}", repo_name=repo_name)
            # We already set result_data["repository"] = f"{full_name}@{sha}" earlier,
            # so this consistent with our check for existing repositories
            # Store the repo_identifier for directory name separately
            dir_identifier = f"{full_name.replace('/', '_')}_{sha[:7]}"  # Use shorter SHA
            result_data["repository_identifier"] = dir_identifier
        else:
            local_path = Path(local_path)
            # If extract-tests flag is enabled, use direct access to avoid copying
            if args.extract_tests:
                # Use the local repository directly
                working_dir = repo_manager.use_local_repository(local_path)
                add_log_entry(f"Using direct access to local repository at {local_path}")
            else:
                # Standard approach for non-extract-tests mode
                working_dir = repo_manager.setup_local_repository(local_path)
                
            repo_name = working_dir.name
            add_log_entry(f"Set up local repository from {local_path}", repo_name=repo_name)
            # We've already set result_data["repository"] = str(local_path) earlier,
            # so this is consistent with our check for existing repositories
            # Use repo name for the output directory
            dir_identifier = repo_name
            result_data["repository_identifier"] = dir_identifier
        
        # Store the project directory for reference
        result_data["project_directory"] = str(working_dir)
        
        add_log_entry(f"Using project identifier: {dir_identifier}")
        add_log_entry(f"Project will be processed in: {working_dir}")
        
        # If extract-tests is enabled, extract test files and write to test.jsonl
        if args.extract_tests:
            add_log_entry("Extracting test files...")
            # For local repositories, never mark as temp_dir to avoid deletion
            is_temp_dir = temp_dir is not None  # Only temp_dir if we created one for GitHub repos
            
            # Double-check we're not accidentally marking a local repo as temporary
            if is_temp_dir and str(working_dir) == str(local_path):
                add_log_entry(f"WARNING: Prevented marking local directory {working_dir} as temporary", level="WARNING")
                is_temp_dir = False
            
            # Check if we're in collect-only mode (used by the wrapper function)
            collecting_only = hasattr(args, '_collect_tests_only') and args._collect_tests_only
            
            # Only attempt to delete the file if we're not in collect-only mode
            if not collecting_only:
                # Always overwrite the test.jsonl file when it's the first repo processed
                if tests_jsonl_path.exists() and not hasattr(args, '_test_file_overwritten'):
                    add_log_entry(f"Overwriting existing test file at {tests_jsonl_path}")
                    # Remove the existing file to start fresh
                    tests_jsonl_path.unlink()
                    # Mark that we've overwritten the file to avoid doing it multiple times
                    args._test_file_overwritten = True
            
            test_files_data = extract_test_files(working_dir, repo_identifier, is_temp_dir)
            
            # Skip if no valid test files found
            if not test_files_data:
                add_log_entry(f"No valid test files found with identified tested files in repository: {repo_identifier}")
                if not (args.collect_only or args.extract_dep):
                    result_data["status"] = "success"
                    result_data["execution"]["elapsed_time"] = time.time() - start_time
                    add_log_entry("Test extraction completed, but no valid test files found")
                    return 0
            else:
                # Create a record to write to test.jsonl
                test_record = {
                    "repository": repo_identifier,
                    "tests": test_files_data
                }
                
                # If we're in collect-only mode, store the test record on the args object
                if collecting_only:
                    args._test_record = test_record
                    add_log_entry(f"Collected {len(test_files_data)} test files for later writing")
                else:
                    # Write to test.jsonl directly if not in collect-only mode
                    try:
                        with open(tests_jsonl_path, "a") as f:
                            f.write(json.dumps(test_record) + "\n")
                        add_log_entry(f"Extracted {len(test_files_data)} test files to {tests_jsonl_path}")
                    except Exception as e:
                        add_log_entry(f"Error writing to test.jsonl: {e}", level="ERROR")
                        result_data["status"] = "error"
                        result_data["error"] = str(e)
                        return 1
                
                # If only extracting tests, finish here without writing to results.jsonl
                if not (args.collect_only or args.extract_dep):
                    result_data["status"] = "success"
                    result_data["execution"]["elapsed_time"] = time.time() - start_time
                    
                    # Skip writing to results.jsonl when using extract-tests
                    add_log_entry("Test extraction completed as requested")
                    return 0
        
        # Extract dependencies - use working_dir
        dependency_extractor = DependencyExtractor(working_dir, logger=logger)
        requirements = dependency_extractor.extract_all_requirements()
        unified_requirements = dependency_extractor.unify_requirements(requirements)
        result_data["dependencies"]["found"] = len(unified_requirements)
        result_data["dependencies"]["details"] = unified_requirements
        
        add_log_entry(f"Extracted {len(unified_requirements)} requirements")
        
        # Define paths for configuration files in the working directory
        requirements_in_path = working_dir / "requirements.in"
        compiled_requirements_path = working_dir / "requirements.txt"
        pyproject_path = working_dir / "pyproject.toml"
        venv_path = working_dir / '.venv'
        
        # Convert to absolute paths to ensure consistency
        requirements_in_path = requirements_in_path.absolute()
        compiled_requirements_path = compiled_requirements_path.absolute()
        pyproject_path = pyproject_path.absolute()
        venv_path = venv_path.absolute()
        
        add_log_entry(f"Using absolute paths: venv_path={venv_path}")
        
        # Create a requirements.in file
        with open(requirements_in_path, 'w') as f:
            f.write('\n'.join(unified_requirements))
        add_log_entry(f"Created requirements.in file at {requirements_in_path}")
        
        # Different handling based on whether UV is being used
        if args.use_uv:
            # Compile requirements with --resolution lowest to ensure compatibility with lower bounds
            add_log_entry("Compiling requirements with UV using --resolution lowest")
            try:
                compiled_result = subprocess.run(
                    ['uv', 'pip', 'compile', 'requirements.in', '--resolution', 'lowest', '--output-file', 'requirements.txt'],
                    cwd=working_dir,
                    check=True,
                    capture_output=True,
                    text=True
                )
                add_log_entry("Successfully compiled requirements with lowest resolution")
                
                # Read the compiled requirements
                if compiled_requirements_path.exists():
                    with open(compiled_requirements_path, 'r') as f:
                        compiled_requirements_content = f.read()
                    
                    # Parse the compiled requirements to get exact versions
                    exact_requirements = []
                    for line in compiled_requirements_content.splitlines():
                        # Skip comments and empty lines
                        if line.strip() and not line.strip().startswith('#'):
                            exact_requirements.append(line.strip())
                    
                    add_log_entry(f"Parsed {len(exact_requirements)} exact requirements with lowest versions")
                    
                    # Use these exact requirements for installation
                    unified_requirements = exact_requirements
                    result_data["compiled_requirements"] = exact_requirements
                else:
                    add_log_entry("Compiled requirements.txt not found, using original requirements", level="WARNING")
            except subprocess.CalledProcessError as e:
                add_log_entry(f"Failed to compile requirements with lowest resolution: {e.stderr}", level="WARNING")
                add_log_entry("Falling back to original requirements", level="WARNING")
        else:
            # When using pip, just copy requirements.in to requirements.txt
            add_log_entry("Copying requirements.in to requirements.txt (using pip)")
            shutil.copy(requirements_in_path, compiled_requirements_path)
            
        # Check if pyproject.toml already exists in the original repo
        original_pyproject_path = working_dir / "pyproject.toml"
        project_already_initialized = original_pyproject_path.exists()
        
        # If pyproject.toml exists in the original repo, copy it to the project directory
        if project_already_initialized and original_pyproject_path != pyproject_path:
            shutil.copy(original_pyproject_path, pyproject_path)
            add_log_entry(f"Copied existing pyproject.toml to {pyproject_path}")
        elif project_already_initialized:
            add_log_entry(f"Using existing pyproject.toml at {pyproject_path}")
        # Initialize installation_results with a default empty list
        installation_results = []
        
        # Initialize project
        if args.use_uv:
            add_log_entry("Initializing project with uv")
            
            try:
                # Install Python 3.10 using uv
                add_log_entry("Installing Python 3.10 using uv")
                result = subprocess.run(
                    ['uv', 'python', 'install', '3.10'],
                    cwd=working_dir,
                    check=True,
                    capture_output=True,
                    text=True
                )
                add_log_entry(f"Python 3.10 installation result: {result.stdout}")
                
                # Pin Python version to 3.10 using uv python pin
                add_log_entry("Pinning Python version to 3.10")
                result = subprocess.run(
                    ['uv', 'python', 'pin', '3.10'],
                    cwd=working_dir,
                    check=True,
                    capture_output=True,
                    text=True
                )
                add_log_entry(f"Python version pinning result: {result.stdout}")
                
                # Now initialize the project or create venv
                if project_already_initialized:
                    add_log_entry("Project already initialized (pyproject.toml exists)")
                    # Just create the venv with Python 3.10
                    result = subprocess.run(
                        ['uv', 'venv', str(venv_path)],
                        cwd=working_dir,
                        check=True,
                        capture_output=True,
                        text=True
                    )
                else:
                    # Initialize project with uv init
                    result = subprocess.run(
                        ['uv', 'init'],
                        cwd=working_dir,
                        check=True,
                        capture_output=True,
                        text=True
                    )
                add_log_entry(f"Virtual environment created at {venv_path} with Python 3.10")
                
                # Install the package in development mode
                try:
                    add_log_entry("Installing Cython")
                    result = subprocess.run(
                        [str(venv_path) + '/bin/pip', 'install', 'Cython'],
                        check=True,
                        capture_output=True,
                        text=True
                    )
                    add_log_entry(f"Successfully installed Cython: {result.stdout.strip()}")

                    add_log_entry("Installing package in development mode (pip install -e .)")
                    result = subprocess.run(
                        [str(venv_path) + '/bin/pip', 'install', '-e', '.'],
                        cwd=working_dir,
                        check=True,
                        capture_output=True,
                        text=True
                    )
                    add_log_entry(f"Successfully installed package in development mode: {result.stdout.strip()}")
                except subprocess.CalledProcessError as e:
                    add_log_entry(f"Failed to install Cython or package in development mode: {e.stderr}", level="WARNING")
                    add_log_entry("Continuing without development mode installation", level="WARNING")
                
                # Install dependencies
                dependency_installer = DependencyInstaller(working_dir, use_uv=args.use_uv, logger=logger)
                add_log_entry(f"Installing {len(unified_requirements)} requirements using {'UV' if args.use_uv else 'pip'}")
                add_log_entry(f"Virtual environment path: {venv_path}, exists: {venv_path.exists()}")
                
                # Check if pip exists in the virtual environment
                if not args.use_uv:
                    if sys.platform == 'win32':
                        pip_path = venv_path / 'Scripts' / 'pip.exe'
                    else:
                        pip_path = venv_path / 'bin' / 'pip'
                    
                    add_log_entry(f"Checking pip path: {pip_path}, exists: {pip_path.exists()}")
                    
                    if not pip_path.exists():
                        add_log_entry(f"pip not found at {pip_path}, trying to install it", level="WARNING")
                        try:
                            python_path = venv_path / 'bin' / 'python' if not sys.platform == 'win32' else venv_path / 'Scripts' / 'python.exe'
                            
                            if python_path.exists():
                                add_log_entry(f"Python found at {python_path}, using it to install pip")
                                subprocess.run(
                                    [str(python_path), '-m', 'ensurepip', '--upgrade'],
                                    check=True,
                                    capture_output=True,
                                    text=True
                                )
                                add_log_entry("Successfully installed pip using ensurepip")
                            else:
                                add_log_entry(f"Python not found at {python_path}", level="ERROR")
                        except Exception as e:
                            add_log_entry(f"Failed to install pip: {str(e)}", level="ERROR")
                
                # Now install requirements
                installation_results = dependency_installer.install_requirements(unified_requirements, venv_path)
                
                # Store installation results in the result data
                result_data["installation_results"] = installation_results
                result_data["dependencies"]["installed"] = sum(1 for r in installation_results if r["success"])
                
                # Check if all dependencies were successfully installed
                if result_data["dependencies"]["installed"] < len(unified_requirements):
                    add_log_entry(f"Failed to install all dependencies. Installed {result_data['dependencies']['installed']} out of {len(unified_requirements)} requirements", level="ERROR")
                    result_data["status"] = "error"
                    result_data["error"] = "Not all dependencies could be installed"
                    
                    # Write the result to results.jsonl
                    with open(results_jsonl_path, "a") as f:
                        f.write(json.dumps(result_data) + "\n")
                    
                    return 1
            except subprocess.CalledProcessError as e:
                add_log_entry(f"Failed to initialize project with UV: {e.stderr}", level="ERROR")
                result_data["status"] = "error"
                result_data["error"] = f"Failed to initialize project with UV: {e.stderr}"
                # Write the result to results.jsonl
                with open(results_jsonl_path, "a") as f:
                    f.write(json.dumps(result_data) + "\n")
                raise RuntimeError(f"Failed to initialize project with UV: {e.stderr}")
        else:
            add_log_entry("Initializing project with standard venv")
            
            try:
                # Create a virtual environment using venv module
                import venv
                add_log_entry(f"Creating virtual environment at {venv_path}")
                venv.create(venv_path, with_pip=True)
                add_log_entry(f"Virtual environment created at {venv_path}")
                
                # Upgrade pip to the latest version
                add_log_entry("Upgrading pip to the latest version")
                
                # Get the path to the pip executable in the virtual environment
                if sys.platform == 'win32':
                    pip_path = venv_path / 'Scripts' / 'pip.exe'
                else:
                    pip_path = venv_path / 'bin' / 'pip'
                
                # Ensure pip_path is absolute
                pip_path = pip_path.absolute()
                
                if pip_path.exists():
                    try:
                        upgrade_cmd = [
                            str(pip_path),
                            'install',
                            '--upgrade',
                            'pip'
                        ]
                        
                        add_log_entry(f"Running pip with command: {' '.join(upgrade_cmd)}")
                        
                        result = subprocess.run(
                            upgrade_cmd,
                            check=True,
                            capture_output=True,
                            text=True
                        )
                        
                        add_log_entry(f"Successfully upgraded pip: {result.stdout.strip()}")
                        
                        # Install the package in development mode
                        try:
                            add_log_entry("Installing Cython")
                            result = subprocess.run(
                                [str(pip_path), 'install', 'Cython'],
                                check=True,
                                capture_output=True,
                                text=True
                            )
                            add_log_entry(f"Successfully installed Cython: {result.stdout.strip()}")

                            add_log_entry("Installing package in development mode (pip install -e .)")
                            result = subprocess.run(
                                [str(pip_path), 'install', '-e', '.'],
                                cwd=working_dir,
                                check=True,
                                capture_output=True,
                                text=True
                            )
                            add_log_entry(f"Successfully installed package in development mode: {result.stdout.strip()}")
                        except subprocess.CalledProcessError as e:
                            add_log_entry(f"Failed to install Cython or package in development mode: {e.stderr}", level="WARNING")
                            add_log_entry("Continuing without development mode installation", level="WARNING")
                    except subprocess.CalledProcessError as e:
                        add_log_entry(f"Failed to upgrade pip or install package in development mode: {e.stderr}", level="WARNING")
                    except Exception as e:
                        add_log_entry(f"Error upgrading pip: {str(e)}", level="WARNING")
                        add_log_entry("Continuing with existing pip version", level="WARNING")
                else:
                    add_log_entry(f"pip not found at {pip_path}, skipping upgrade", level="WARNING")
                
            except Exception as e:
                add_log_entry(f"Failed to initialize project with venv: {str(e)}", level="ERROR")
                result_data["status"] = "error"
                result_data["error"] = f"Failed to initialize project with venv: {str(e)}"
                # Write the result to results.jsonl
                with open(results_jsonl_path, "a") as f:
                    f.write(json.dumps(result_data) + "\n")
                raise RuntimeError(f"Failed to initialize project with venv: {str(e)}")
            
            # Install dependencies
            dependency_installer = DependencyInstaller(working_dir, use_uv=args.use_uv, logger=logger)
            add_log_entry(f"Installing {len(unified_requirements)} requirements using {'UV' if args.use_uv else 'pip'}")
            add_log_entry(f"Virtual environment path: {venv_path}, exists: {venv_path.exists()}")
            
            # Now install requirements
            installation_results = dependency_installer.install_requirements(unified_requirements, venv_path)
            
            # Store installation results in the result data
            result_data["installation_results"] = installation_results
            result_data["dependencies"]["installed"] = sum(1 for r in installation_results if r["success"])
            
            # Check if all dependencies were successfully installed
            if result_data["dependencies"]["installed"] < len(unified_requirements):
                add_log_entry(f"Failed to install all dependencies. Installed {result_data['dependencies']['installed']} out of {len(unified_requirements)} requirements", level="ERROR")
                result_data["status"] = "error"
                result_data["error"] = "Not all dependencies could be installed"
                
                # Write the result to results.jsonl
                with open(results_jsonl_path, "a") as f:
                    f.write(json.dumps(result_data) + "\n")
                
                return 1
        
        # If collect-only mode is enabled, only collect tests without running them
        if args.collect_only:
            add_log_entry("Running in collect-only mode", level="INFO")
            
            # Run test collection
            test_runner = TestRunner(working_dir, venv_path=venv_path, use_uv=args.use_uv, logger=logger, timeout=args.timeout)
            
            # Collect tests
            try:
                test_collection = test_runner.collect_tests()
                
                # Always set status to failure in collect-only mode
                result_data["status"] = "failure"
                result_data["tests"] = {
                    "found": len(test_collection.get("tests", [])),
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "details": []
                }
                result_data["test_collection"] = test_collection
                
                # Write the result to results.jsonl
                with open(results_jsonl_path, "a") as f:
                    f.write(json.dumps(result_data) + "\n")
                
                add_log_entry(f"Collected {len(test_collection.get('tests', []))} test cases", level="INFO")
                
                return 1  # Return failure status as requested
            except Exception as e:
                add_log_entry(f"Error collecting tests: {str(e)}", level="ERROR")
                result_data["status"] = "error"
                result_data["error"] = str(e)
                
                # Write the result to results.jsonl
                with open(results_jsonl_path, "a") as f:
                    f.write(json.dumps(result_data) + "\n")
                
                return 1
        
        # Run tests
        test_runner = TestRunner(working_dir, venv_path=venv_path, use_uv=args.use_uv, logger=logger, timeout=args.timeout)
        add_log_entry("Looking for tests in the project's code (excluding virtual environment)")
        
        # Check for project-specific tests first
        test_files = test_runner.find_tests()
        
        if not test_files:
            add_log_entry("No project-specific tests found. The project may not have tests.", level="WARNING")
            result_data["tests"]["found"] = 0
            result_data["tests"]["passed"] = 0
            result_data["tests"]["failed"] = 0
            result_data["tests"]["skipped"] = 0
            
            add_log_entry("Setting status to skip since no tests were found")
            result_data["status"] = "skip"
        else:
            add_log_entry(f"Found {len(test_files)} test files in the project")
            
            # Run test discovery
            test_results = test_runner.run_tests()
            
            # Check for errors in test details and count individual test cases
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
            
            # If we have individual tests, use those for more accurate counts
            if "individual_tests" in test_results and test_results["individual_tests"]:
                individual_tests = test_results["individual_tests"]
                success_count = sum(1 for t in individual_tests if t.get("status") == "passed")
                failure_count = sum(1 for t in individual_tests if t.get("status") in ["failed", "failure", "error"])
                skip_count = sum(1 for t in individual_tests if t.get("status") == "skipped")
                total_test_cases = len(individual_tests)
                has_failures = failure_count > 0
                add_log_entry(f"Using counts from {len(individual_tests)} individual tests: {success_count} passed, {failure_count} failed, {skip_count} skipped")
                
                # Include individual tests in result data
                result_data["individual_tests"] = test_results["individual_tests"]
            
            # If no summary line found and no individual tests, fall back to counting individual results
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

            # Store test results in the result data
            result_data["tests"]["found"] = total_test_cases
            result_data["tests"]["passed"] = success_count
            result_data["tests"]["failed"] = failure_count
            result_data["tests"]["skipped"] = skip_count
            result_data["tests"]["details"] = test_results["test_results"]
            
            # Add individual test results if available
            if "individual_tests" in test_results:
                result_data["individual_tests"] = test_results["individual_tests"]
                add_log_entry(f"Collected {len(test_results['individual_tests'])} individual test results")
                
                # Create lists of test names for each test file
                tests_by_file = {}
                
                # Process individual tests to organize them by file
                for test in test_results["individual_tests"]:
                    file_path = test.get("file_path", "")
                    test_name = test.get("name", "")
                    status = test.get("status", "")
                    
                    if not file_path:
                        continue
                    
                    # Initialize entry for this file if needed
                    if file_path not in tests_by_file:
                        tests_by_file[file_path] = {
                            "passed_tests": [],
                            "failed_tests": [],
                            "skipped_tests": []
                        }
                    
                    # Add test name to appropriate list based on status
                    if status == "passed":
                        tests_by_file[file_path]["passed_tests"].append(test_name)
                    elif status in ["failed", "failure", "error"]:
                        tests_by_file[file_path]["failed_tests"].append(test_name)
                    elif status == "skipped":
                        tests_by_file[file_path]["skipped_tests"].append(test_name)
                
                # Update test file data in result_data with test name lists
                for i, test_file in enumerate(test_results.get("test_files", [])):
                    file_path = test_file.get("path", "")
                    if file_path in tests_by_file:
                        # Add test name lists to the test file data
                        test_results["test_files"][i]["passed_tests"] = tests_by_file[file_path]["passed_tests"]
                        test_results["test_files"][i]["failed_tests"] = tests_by_file[file_path]["failed_tests"]
                        test_results["test_files"][i]["skipped_tests"] = tests_by_file[file_path]["skipped_tests"]
                        
                        # Log the counts for this file
                        add_log_entry(f"File {file_path}: {len(tests_by_file[file_path]['passed_tests'])} passed, "
                                     f"{len(tests_by_file[file_path]['failed_tests'])} failed, "
                                     f"{len(tests_by_file[file_path]['skipped_tests'])} skipped")
                
                # Ensure the test lists are in the final output structure
                if "test_files" not in result_data:
                    result_data["test_files"] = []
                    
                # Create test_files in result_data from test_results
                for test_file in test_results.get("test_files", []):
                    file_path = test_file.get("path", "")
                    
                    # Find if the file already exists in result_data
                    existing_file = None
                    for f in result_data["test_files"]:
                        if f.get("path") == file_path:
                            existing_file = f
                            break
                    
                    if existing_file:
                        # Update existing file entry
                        if "passed_tests" in test_file:
                            existing_file["passed_tests"] = test_file["passed_tests"]
                        if "failed_tests" in test_file:
                            existing_file["failed_tests"] = test_file["failed_tests"]
                        if "skipped_tests" in test_file:
                            existing_file["skipped_tests"] = test_file["skipped_tests"]
                    else:
                        # Create new file entry
                        file_entry = {
                            "path": file_path,
                            "status": test_file.get("status", "unknown"),
                            "tested_files": []
                        }
                        
                        # Copy test lists
                        if "passed_tests" in test_file:
                            file_entry["passed_tests"] = test_file["passed_tests"]
                        if "failed_tests" in test_file:
                            file_entry["failed_tests"] = test_file["failed_tests"]
                        if "skipped_tests" in test_file:
                            file_entry["skipped_tests"] = test_file["skipped_tests"]
                            
                        result_data["test_files"].append(file_entry)
                
                add_log_entry(f"Ensured {len(result_data.get('test_files', []))} test files in result_data have test lists")
            
            # Update test status based on actual failures, successes, and skips
            if total_test_cases == 0:
                add_log_entry("Setting status to skip - no test cases were found")
                result_data["status"] = "skip"
            elif skip_count > 0 and skip_count == total_test_cases:
                # Check if all skipped tests were due to "No test functions found"
                all_no_tests = all("No test functions found" in detail.get("message", "") 
                                 for detail in test_results.get("test_results", []))
                if all_no_tests:
                    add_log_entry("Setting status to skip because no test functions were found in any test files")
                    result_data["status"] = "skip"
                else:
                    add_log_entry("Setting status to failure because all tests were explicitly skipped")
                    result_data["status"] = "failure"
            elif has_failures:
                if success_count > 0:
                    add_log_entry(f"Setting status to partial_success because {success_count} test cases passed and {failure_count} test cases failed")
                    result_data["status"] = "partial_success"
                else:
                    add_log_entry("Setting status to failure due to test failures in output")
                    result_data["status"] = "failure"
            else:
                add_log_entry(f"Setting status to success - all {success_count} test cases passed")
                result_data["status"] = "success"
                
            # Log detailed test counts
            add_log_entry(f"Test summary: {total_test_cases} total cases - {success_count} passed, {failure_count} failed, {skip_count} skipped")
        
        # Generate summary
        end_time = time.time()
        elapsed_time = end_time - start_time
        
        # Update result data with summary information
        result_data["execution"]["elapsed_time"] = elapsed_time
        result_data["dependencies"]["installed"] = sum(1 for r in installation_results if r["success"])
        
        # Log the current test counts before final update
        add_log_entry(f"Test counts before final update: found={result_data['tests']['found']}, passed={result_data['tests']['passed']}, failed={result_data['tests']['failed']}, skipped={result_data['tests']['skipped']}")
        
        # Log individual test counts if available
        if "individual_tests" in result_data:
            individual_count = len(result_data["individual_tests"])
            add_log_entry(f"Individual test counts: {individual_count} total individual tests collected")

        add_log_entry(f"Process completed in {elapsed_time:.2f} seconds")
        add_log_entry(f"Project configured in {working_dir}")
        
        # Ensure test file details include individual test names
        if "test_files" in result_data:
            for test_file in result_data["test_files"]:
                # Make sure the test_file has the required fields
                if "tests" not in test_file:
                    test_file["tests"] = []
                
                # Make sure summary is present
                if "summary" not in test_file:
                    test_file["summary"] = {
                        "passed_tests": sum(1 for t in test_file.get("tests", []) if t.get("status") == "passed"),
                        "failed_tests": sum(1 for t in test_file.get("tests", []) if t.get("status") in ["failure", "error"]),
                        "skipped_tests": sum(1 for t in test_file.get("tests", []) if t.get("status") == "skipped")
                    }
        
        # If we have individual_tests but empty test lists in test_files, populate them
        if "individual_tests" in result_data and "test_files" in result_data:
            individual_tests = result_data["individual_tests"]
            
            # Group tests by file path
            tests_by_file = {}
            for test in individual_tests:
                file_path = test.get("file_path", "")
                if not file_path:
                    continue
                
                if file_path not in tests_by_file:
                    tests_by_file[file_path] = []
                
                # Add complete test data
                tests_by_file[file_path].append({
                    "name": test.get("name", ""),
                    "classname": test.get("classname", ""),
                    "status": test.get("status", ""),
                    "message": test.get("message", "")
                })
            
            # Update test file entries with the test data
            for i, test_file in enumerate(result_data["test_files"]):
                file_path = test_file.get("path", "")
                
                # If this file has individual tests and the list is empty, populate it
                if file_path in tests_by_file and not test_file.get("tests"):
                    test_file["tests"] = tests_by_file[file_path]
                    
                    # Update summary counts
                    if "summary" not in test_file:
                        test_file["summary"] = {}
                    
                    test_file["summary"]["passed_tests"] = sum(1 for t in test_file["tests"] if t["status"] == "passed")
                    test_file["summary"]["failed_tests"] = sum(1 for t in test_file["tests"] if t["status"] in ["failure", "error"])
                    test_file["summary"]["skipped_tests"] = sum(1 for t in test_file["tests"] if t["status"] == "skipped")
        
        # Write the final result to results.jsonl
        with open(results_jsonl_path, "a") as f:
            f.write(json.dumps(result_data) + "\n")
        
        add_log_entry(f"Results written to {results_jsonl_path}")
        
        # Clean up the project directory to save disk space
        try:
            cleanup_resources(working_dir, venv_path, logger=logger)
        except Exception as e:
            add_log_entry(f"Warning: Failed to clean up resources: {e}", level="WARNING")
        
        return 0
    
    except Exception as e:
        error_message = str(e)
        add_log_entry(f"An error occurred: {error_message}", level="ERROR", exc_info=True)
        
        # Update result data with error information
        result_data["status"] = "error"
        result_data["error"] = error_message
        
        # Write the error result to results.jsonl
        with open(results_jsonl_path, "a") as f:
            f.write(json.dumps(result_data) + "\n")
        
        # Clean up the project directory in case of error too
        if 'working_dir' in locals() and working_dir.exists():
            try:
                cleanup_resources(working_dir, venv_path, logger=logger)
            except Exception as cleanup_error:
                add_log_entry(f"Warning: Failed to remove project directory after error: {cleanup_error}", level="WARNING")
        
        return 1


def extract_test_files(repository_path: Path, repository_identifier: str, is_temp_dir: bool = False) -> List[Dict[str, Any]]:
    """
    Extract test files from a repository.
    
    Args:
        repository_path: Path to the repository directory
        repository_identifier: Unique identifier for the repository
        is_temp_dir: Whether the repository path is a temporary directory
    
    Returns:
        List[Dict[str, Any]]: List of dictionaries containing test files with their paths, content, and the project files they test
    """
    # Initialize the TestRunner to find test files
    logger = logging.getLogger(__name__)
    if is_temp_dir:
        logger.info(f"Repository at {repository_path} is a temporary directory and will be cleaned up after extraction")
    else:
        logger.info(f"Repository at {repository_path} is not a temporary directory and will be preserved")
    
    test_runner = TestRunner(repository_path, logger=logger)
    
    try:
        # Find test files in the repository
        test_files = test_runner.find_tests()
        
        if not test_files:
            logger.info(f"No test files found in repository: {repository_identifier}")
            # As a backup, try a simple glob for any Python files if no tests were found
            # This helps with repositories that have unconventional test naming patterns
            backup_files = list(repository_path.glob("**/*.py"))
            if backup_files:
                logger.info(f"Found {len(backup_files)} Python files in repository. Checking for potential test files...")
                for file_path in backup_files:
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                            content = f.read().lower()
                            # Check if file might be a test file based on content
                            test_indicators = [
                                'import unittest', 'import pytest', '@pytest', 'pytest', 
                                'testcase', 'test_', 'assert', 'mock'
                            ]
                            if any(indicator in content for indicator in test_indicators):
                                rel_path = file_path.relative_to(repository_path)
                                logger.info(f"Detected potential test file from content: {rel_path}")
                                test_files.append(file_path)
                    except Exception as e:
                        logger.debug(f"Error analyzing potential test file {file_path}: {e}")
                
                # Take only the top 10 files to avoid extracting too many non-test files
                if len(test_files) > 10:
                    logger.info(f"Limiting to 10 potential test files out of {len(test_files)}")
                    test_files = test_files[:10]
            
            if not test_files:
                return []
            
        # Extract file paths, contents, and analyze imports
        tests_data = []
        skipped_files = 0
        for test_file in test_files:
            try:
                # Skip if file is too large (>1MB) to avoid memory issues
                if test_file.stat().st_size > 1024 * 1024:
                    logger.warning(f"Skipping large test file (>1MB): {test_file}")
                    skipped_files += 1
                    continue
                
                # Get the relative path within the repository
                relative_path = test_file.relative_to(repository_path)
                
                # Read the file content
                with open(test_file, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                
                # Extract local project imports
                tested_files = extract_local_imports_from_test_file(test_file, repository_path, logger)

                # Skip files that don't test any project files
                if not tested_files:
                    logger.info(f"Including test file with empty tested_files: {relative_path}")
                
                # Ensure no duplicates in the tested_files list - convert to set and back to list
                if tested_files:
                    # Remove duplicates while preserving order
                    seen = set()
                    unique_tested_files = []
                    for item in tested_files:
                        if item not in seen:
                            seen.add(item)
                            unique_tested_files.append(item)
                    tested_files = unique_tested_files
                    
                    if len(unique_tested_files) < len(tested_files):
                        logger.info(f"Removed {len(tested_files) - len(unique_tested_files)} duplicate entries from tested_files")
                
                # Add the file data to the list
                tests_data.append({
                    "path": str(relative_path),
                    "content": content,
                    "tested_files": tested_files
                })
                
                if tested_files:
                    logger.info(f"Extracted test file: {relative_path} (tests {len(tested_files)} project files)")
                else:
                    logger.info(f"Extracted test file: {relative_path} (no identified tested files)")
            except UnicodeDecodeError as ude:
                logger.warning(f"Skipping test file with encoding issues: {test_file}: {str(ude)}")
                skipped_files += 1
            except Exception as e:
                logger.warning(f"Failed to extract test file {test_file}: {str(e)}")
                skipped_files += 1
        
        logger.info(f"Extracted {len(tests_data)} test files, skipped {skipped_files} files due to errors")
        
        # If we found more than 50 test files, limit to 50 to avoid potential issues
        if len(tests_data) > 50:
            logger.info(f"Limiting to 50 test files out of {len(tests_data)}")
            tests_data = tests_data[:50]
            
        return tests_data
    finally:
        # Clean up temporary directory if one was created
        if is_temp_dir and repository_path.exists():
            try:
                logger.info(f"Cleaning up temporary directory: {repository_path}")
                shutil.rmtree(repository_path)
                logger.info(f"Successfully cleaned up temporary directory: {repository_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up temporary directory {repository_path}: {str(e)}")

def extract_local_imports_from_test_file(test_file: Path, repository_path: Path, logger) -> List[str]:
    """
    Extract local (within repository) imports from a test file.
    Uses AST to find import statements and resolves them to actual files.
    
    Args:
        test_file: Path to the test file
        repository_path: Path to the repository root
        logger: Logger instance
    
    Returns:
        List of file paths that are imported by the test file. 
        Directories are marked with a trailing slash.
    """
    try:
        with open(test_file, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        # First try with AST for more precise analysis
        try:
            tree = ast.parse(content)
        except SyntaxError:
            # Fall back to regex-based extraction if AST parsing fails
            logger.debug(f"AST parsing failed for {test_file}, falling back to regex")
            return extract_imports_with_regex(test_file, repository_path, content, logger)
        
        # Track imports
        tested_files = set()
        all_imports = set()
        
        def add_module_path(module_name: str, is_from_import: bool = False):
            """Helper function to add a module path and check its existence"""
            # Convert dot notation to path notation
            module_path = module_name.replace('.', '/')
            
            # Try direct file match first
            py_file = repository_path / (module_path + '.py')
            dir_path = repository_path / module_path
            init_file = dir_path / '__init__.py'
            
            if py_file.exists():
                tested_files.add(module_path + '.py')
                return True
            elif init_file.exists():
                # If it's a directory with __init__.py, mark it as a package
                tested_files.add(module_path + '/')
                return True
            
            # For from imports, also check each segment of the path
            if is_from_import:
                parts = module_path.split('/')
                found = False
                for i in range(len(parts)):
                    partial_path = '/'.join(parts[:i+1])
                    py_path = repository_path / (partial_path + '.py')
                    dir_path = repository_path / partial_path
                    init_path = dir_path / '__init__.py'
                    
                    if py_path.exists():
                        tested_files.add(partial_path + '.py')
                        found = True
                    elif init_path.exists():
                        tested_files.add(partial_path + '/')
                        found = True
                return found
            return False
        
        # Process all import statements in the AST
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    module_name = name.name
                    all_imports.add(module_name)
                    add_module_path(module_name)
            
            elif isinstance(node, ast.ImportFrom):
                # Handle relative imports (level > 0)
                if node.level > 0:
                    # Get the importing file's directory to resolve relative imports
                    importing_file_dir = test_file.parent
                    
                    # Go up by 'level' directories
                    target_dir = importing_file_dir
                    for _ in range(node.level):
                        if target_dir == repository_path:
                            break
                        target_dir = target_dir.parent
                    
                    # Determine the module path
                    if node.module:
                        module_path = node.module.replace('.', '/')
                        resolved_path = target_dir / module_path
                    else:
                        resolved_path = target_dir
                    
                    # Convert to path relative to repository root
                    try:
                        relative_resolved_path = resolved_path.relative_to(repository_path)
                        module_str = str(relative_resolved_path)
                        
                        # Check if it exists as a file or directory with __init__.py
                        py_file = resolved_path.with_suffix('.py')
                        init_file = resolved_path / '__init__.py'
                        
                        if py_file.exists():
                            tested_files.add(module_str + '.py')
                        elif init_file.exists():
                            tested_files.add(module_str + '/')
                        
                        # Also check imported names for potential modules
                        for imported_name in node.names:
                            name = imported_name.name
                            if name == '*':
                                continue
                            
                            potential_module = resolved_path / name
                            potential_module_py = potential_module.with_suffix('.py')
                            potential_module_init = potential_module / '__init__.py'
                            
                            if potential_module_py.exists():
                                try:
                                    relative_module = potential_module_py.relative_to(repository_path)
                                    tested_files.add(str(relative_module))
                                except ValueError:
                                    pass
                            elif potential_module_init.exists():
                                try:
                                    relative_module = potential_module.relative_to(repository_path)
                                    tested_files.add(str(relative_module) + '/')
                                except ValueError:
                                    pass
                    except ValueError:
                        logger.warning(f"Could not resolve relative import in {test_file}")
                
                # Handle absolute imports (level = 0)
                else:
                    if node.module:
                        module_name = node.module
                        all_imports.add(module_name)
                        
                        # Add the base module
                        add_module_path(module_name, True)
                        
                        # Also check for the imported items if they might be submodules
                        for imp_name in node.names:
                            if imp_name.name == '*':
                                continue
                            
                            # Try both as a module and as part of the parent module
                            full_name = f"{module_name}.{imp_name.name}"
                            all_imports.add(full_name)
                            add_module_path(full_name, True)
        
        # If we found nothing with AST, try regex as a backup
        if not tested_files:
            logger.debug(f"AST found no imports, trying regex as backup")
            regex_results = extract_imports_with_regex(test_file, repository_path, content, logger)
            tested_files.update(regex_results)
        
        # Special handling for common patterns
        # If we see imports from 'app', make sure to include the app directory
        if any('app.' in imp for imp in all_imports) or 'app' in all_imports:
            app_dir = repository_path / 'app'
            if app_dir.exists() and (app_dir / '__init__.py').exists():
                tested_files.add('app/')
        
        # Filter out directories if they only exist because we have more specific files
        result = list(tested_files)
        final_results = []
        for path in result:
            if path.endswith('/'):
                # Only keep directories that were directly imported
                has_specific_files = any(
                    other_path.startswith(path) and not other_path.endswith('/')
                    for other_path in result
                )
                if not has_specific_files or path == 'app/':  # Always keep app/ directory
                    final_results.append(path)
            else:
                final_results.append(path)
        
        # If we filtered too much, return the original
        if not final_results and tested_files:
            return sorted(list(tested_files))
        
        return sorted(final_results)
    
    except Exception as e:
        logger.error(f"Error extracting imports from {test_file}: {str(e)}")
        # In case of errors, try with regex as a fallback
        try:
            return extract_imports_with_regex(test_file, repository_path, content, logger)
        except:
            return []

def extract_imports_with_regex(test_file: Path, repository_path: Path, content: str, logger) -> List[str]:
    """
    Extract import statements from a test file using regex as a fallback method.
    
    Args:
        test_file: Path to the test file
        repository_path: Path to the repository root
        content: Content of the test file
        logger: Logger instance
    
    Returns:
        List of import paths found in the test file.
    """
    # Match import statements more broadly
    import_regex = re.compile(r'^(?:[ \t]*)import\s+([a-zA-Z0-9_\.]+)', re.MULTILINE)
    from_import_regex = re.compile(r'^(?:[ \t]*)from\s+([a-zA-Z0-9_\.]+)\s+import\s+([a-zA-Z0-9_\.\,\s\(\)\*]+)', re.MULTILINE)
    # Add pattern for relative imports
    relative_import_regex = re.compile(r'^(?:[ \t]*)from\s+(\.+)([a-zA-Z0-9_\.]*)\s+import\s+([a-zA-Z0-9_\.\,\s\(\)\*]+)', re.MULTILINE)
    
    # Track imports
    tested_files = set()
    all_imports = set()  # Track all import strings for reference
    
    # Process all import statements in the content
    for match in import_regex.finditer(content):
        import_name = match.group(1)
        all_imports.add(import_name)
        module_path = import_name.replace('.', '/')
        
        # Try direct file match first
        py_file = repository_path / (module_path + '.py')
        dir_path = repository_path / module_path
        init_file = dir_path / '__init__.py'
        
        if py_file.exists():
            tested_files.add(module_path + '.py')
        elif init_file.exists():
            tested_files.add(module_path + '/')
        
        # Also check each segment of the import path
        parts = module_path.split('/')
        for i in range(len(parts)):
            partial_path = '/'.join(parts[:i+1])
            py_path = repository_path / (partial_path + '.py')
            dir_path = repository_path / partial_path
            init_path = dir_path / '__init__.py'
            
            if py_path.exists():
                tested_files.add(partial_path + '.py')
            elif init_path.exists():
                tested_files.add(partial_path + '/')
    
    # Process from imports with a more comprehensive approach
    for match in from_import_regex.finditer(content):
        from_module = match.group(1)
        all_imports.add(from_module)
        imported_items_str = match.group(2)
        
        # Handle multiline imports with parentheses
        imported_items = []
        if '(' in imported_items_str and ')' in imported_items_str:
            # For complex imports that might span multiple lines
            imported_items_str = imported_items_str.replace('(', '').replace(')', '')
        
        # Split and clean up the imported items
        imported_items.extend([item.strip() for item in imported_items_str.split(',') if item.strip()])
        
        # Convert module to path
        module_path = from_module.replace('.', '/')
        
        # Check for the module itself
        py_file = repository_path / (module_path + '.py')
        dir_path = repository_path / module_path
        init_file = dir_path / '__init__.py'
        
        if py_file.exists():
            tested_files.add(module_path + '.py')
        elif init_file.exists():
            tested_files.add(module_path + '/')
        
        # Also check each segment of the import path
        parts = module_path.split('/')
        for i in range(len(parts)):
            partial_path = '/'.join(parts[:i+1])
            py_path = repository_path / (partial_path + '.py')
            dir_path = repository_path / partial_path
            init_path = dir_path / '__init__.py'
            
            if py_path.exists():
                tested_files.add(partial_path + '.py')
            elif init_path.exists():
                tested_files.add(partial_path + '/')
        
        # Check each imported item for potential submodules
        for item in imported_items:
            # Skip wildcard imports for submodule checks
            if item == '*':
                continue
                
            # Get the first part of potentially multi-part names (e.g., "name as alias")
            item_name = item.split(' ')[0]
            
            # Skip if it's not a valid identifier
            if not item_name or not item_name[0].isalpha():
                continue
                
            full_name = f"{from_module}.{item_name}"
            all_imports.add(full_name)
            full_path = full_name.replace('.', '/')
            
            py_path = repository_path / (full_path + '.py')
            dir_path = repository_path / full_path
            init_path = dir_path / '__init__.py'
            
            if py_path.exists():
                tested_files.add(full_path + '.py')
            elif init_path.exists():
                tested_files.add(full_path + '/')
    
    # Process relative imports
    for match in relative_import_regex.finditer(content):
        dots = match.group(1)  # dots indicating level
        level = len(dots)       # number of dots = number of levels to go up
        
        from_module = match.group(2)  # module path after the dots
        imported_items_str = match.group(3)  # imported items
        
        # Handle multiline imports with parentheses
        imported_items = []
        if '(' in imported_items_str and ')' in imported_items_str:
            imported_items_str = imported_items_str.replace('(', '').replace(')', '')
        
        # Split and clean up the imported items
        imported_items.extend([item.strip() for item in imported_items_str.split(',') if item.strip()])
        
        # Get the importing file's directory to resolve relative imports
        importing_file_dir = test_file.parent
        
        # Go up by 'level' directories
        target_dir = importing_file_dir
        for _ in range(level):
            if target_dir == repository_path:
                # Don't go beyond the repository root
                logger.warning(f"Relative import in {test_file} tried to go beyond repository root")
                break
            target_dir = target_dir.parent
        
        # Combine with the rest of the module path
        if from_module:
            module_path = from_module.replace('.', '/')
            resolved_path = target_dir / module_path
        else:
            resolved_path = target_dir
        
        # Convert resolved path to be relative to repository root for consistency
        try:
            relative_resolved_path = resolved_path.relative_to(repository_path)
            
            # Check if the module exists as a file or directory
            py_file = resolved_path.with_suffix('.py')
            init_file = resolved_path / '__init__.py'
            
            if py_file.exists():
                tested_files.add(str(relative_resolved_path) + '.py')
            elif init_file.exists():
                tested_files.add(str(relative_resolved_path) + '/')
            
            # Also check for imported items as potential submodules
            for item in imported_items:
                # Skip wildcard imports for submodule checks
                if item == '*':
                    continue
                    
                # Get the first part of potentially multi-part names
                item_name = item.split(' ')[0]
                
                # Skip if it's not a valid identifier
                if not item_name or not item_name[0].isalpha():
                    continue
                
                # Check if the item exists as a module
                if from_module:
                    submodule_path = resolved_path / item_name
                else:
                    submodule_path = resolved_path / item_name
                
                submodule_py = submodule_path.with_suffix('.py')
                submodule_init = submodule_path / '__init__.py'
                
                if submodule_py.exists():
                    relative_submodule = submodule_py.relative_to(repository_path)
                    tested_files.add(str(relative_submodule))
                elif submodule_init.exists():
                    relative_submodule = submodule_path.relative_to(repository_path)
                    tested_files.add(str(relative_submodule) + '/')
        
        except ValueError as e:
            # This happens if resolved_path is not under repository_path
            logger.warning(f"Could not resolve relative import in {test_file}: {e}")
    
    # Clean up results - filter out duplicates and nested directories
    result = list(tested_files)
    
    # Apply the same filtering logic as before for directories
    final_results = []
    for path in result:
        # If this path is a directory (ends with '/')
        if path.endswith('/'):
            # Check if we already have more specific files in this directory
            has_specific_files = any(
                other_path.startswith(path) and not other_path.endswith('/') 
                for other_path in result
            )
            
            # Only keep the directory if we don't have specific files within it
            # or it was directly imported
            if not has_specific_files:
                final_results.append(path)
        else:
            final_results.append(path)
    
    # If we filtered too much, return the original
    if not final_results and tested_files:
        return sorted(list(tested_files))
        
    return sorted(final_results)

def is_test_file(file_path: str) -> bool:
    """
    Check if a file path is a test file based on common naming patterns.
    
    Args:
        file_path (str): File path to check
        
    Returns:
        bool: True if the file appears to be a test file, False otherwise
    """
    # Normalize path for consistent matching
    file_path = file_path.lower().replace('\\', '/')
    
    # Return False for non-python files
    if not file_path.endswith('.py'):
        return False
    
    # Test directory patterns
    directory_patterns = ['/tests/', '/test/', '/pytest/', '/pytests/', '/cases/', '/testcases/', '/testcase/']
    
    # Test file name patterns
    filename_patterns = [
        'test_', '_test', 'tests_', '_tests',
        'unittest', 'pytest', 'conftest',
        '_spec', 'spec_', '_check', 'check_',
        '_suite', 'suite_', 'fixture'
    ]
    
    # First check directory patterns
    if any(pattern in file_path for pattern in directory_patterns):
        return True
    
    # Then check file name patterns
    filename = file_path.split('/')[-1]
    if any(pattern in filename for pattern in filename_patterns):
        return True
    
    return False


def extract_imports_from_test_files(test_files, logger):
    """
    Extract import statements from test files to identify required packages.
    
    Args:
        test_files: List of Path objects pointing to test files
        logger: Logger for reporting
    
    Returns:
        List[str]: List of potential package names to install
    """
    import_pattern = re.compile(r'^(?:import|from)\s+([a-zA-Z0-9_\.]+)')
    standard_libs = set([
        "os", "sys", "re", "json", "time", "datetime", "collections", "unittest", 
        "pathlib", "math", "random", "itertools", "functools", "typing",
        "subprocess", "shutil", "tempfile", "logging"
    ])
    
    # Extract all imports from test files
    all_imports = set()
    for test_file in test_files:
        try:
            with open(test_file, 'r', encoding='utf-8', errors='replace') as f:
                content = f.readlines()
                
            for line in content:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                match = import_pattern.match(line)
                if match:
                    import_name = match.group(1).split('.')[0]
                    # Filter out standard libs
                    if import_name not in standard_libs:
                        all_imports.add(import_name)
        except Exception as e:
            logger.warning(f"Failed to extract imports from {test_file}: {e}")
    
    # Filter out pytest itself (will be installed separately)
    all_imports.discard("pytest")
    
    # Remove potential local package names
    return list(all_imports)


def process_test_repo(args: argparse.Namespace, repo_data: Dict, workspace_dir: Path, index: int) -> int:
    """
    Process a single repository's tests from the test.jsonl data.
    
    Args:
        args: Command line arguments
        repo_data: Repository data from test.jsonl
        workspace_dir: Path to the workspace directory
        index: Index of the repository (for naming)
    
    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
    start_time = time.time()
    repo_workspace = None
    
    # Configure logging for this process
    logger = configure_process_logging(args.verbose)
    
    # Initialize test_results.jsonl file
    output_dir = Path(args.output_dir)
    test_results_jsonl_path = output_dir / "test_results.jsonl"
    
    # Extract repository identifier
    repo_identifier = repo_data.get("repository", f"unknown_repo_{index}")
    
    # Initialize result data structure
    result_data = {
        "repository": repo_identifier,
        "status": "running",
        "configuration": {
            "output_directory": str(output_dir),
            "workspace_directory": str(workspace_dir),
            "timeout": args.timeout
        },
        "tests": {
            "found": len(repo_data.get("tests", [])),
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "details": []
        },
        "execution": {
            "start_time": start_time,
            "elapsed_time": 0
        }
    }
    
    def add_log_entry(message: str, level: str = "INFO", **kwargs):
        """Add a log entry to the logger only."""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if level == "INFO":
            logger.info(message)
        elif level == "WARNING":
            logger.warning(message)
        elif level == "ERROR":
            logger.error(message)
    
    try:
        # Create a directory for this repository's tests
        sanitized_name = re.sub(r'[^\w-]', '_', repo_identifier)[:50]  # Limit length and sanitize
        repo_workspace = Path(workspace_dir) / f"{sanitized_name}_{index}"
        repo_workspace.mkdir(parents=True, exist_ok=True)
        add_log_entry(f"Created workspace for repository: {repo_workspace}")
        
        # Extract tests from the repository data
        tests = repo_data.get("tests", [])
        if not tests:
            add_log_entry(f"No tests found for repository: {repo_identifier}", level="WARNING")
            result_data["status"] = "skip"
            result_data["tests"]["found"] = 0
            
            # Skip writing results
            return 0
        
        # Create test files in the repository workspace
        for test_info in tests:
            test_path = test_info.get("path")
            test_content = test_info.get("content")
            
            if test_path and test_content:
                # Create the full path
                full_path = repo_workspace / test_path
                
                # Create parent directories if they don't exist
                full_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Write the test file
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(test_content)
                
                add_log_entry(f"Created test file: {test_path}")
            else:
                add_log_entry(f"Invalid test info, missing path or content: {test_info}", level="WARNING")
        
        # Find test files
        test_files = []
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
        
        for pattern in test_patterns:
            found_files = list(repo_workspace.glob(pattern))
            test_files.extend(found_files)
        
        # Remove duplicates and sort
        test_files = sorted(set(test_files))
        
        # If we have explicit test files specified in repo_data, use ONLY those
        if "test_files" in repo_data and repo_data["test_files"]:
            add_log_entry("Using only specified test files from repo data")
            specified_test_paths = [test_info.get("path") for test_info in repo_data["test_files"] if "path" in test_info]
            
            if specified_test_paths:
                add_log_entry(f"Specified test paths: {specified_test_paths}")
                
                # Extract test file names (without paths) for flexible matching
                specified_file_names = [Path(file_path).name for file_path in specified_test_paths]
                add_log_entry(f"Specified file names: {specified_file_names}")
                
                # Filter test files to only include those specified
                filtered_test_files = []
                for test_file in test_files:
                    test_file_rel = test_file.relative_to(repo_workspace)
                    test_file_str = str(test_file_rel)
                    test_file_name = test_file.name
                    
                    # Include file if its path contains a specified path OR if just the filename matches
                    if any(specified_path in test_file_str for specified_path in specified_test_paths) or test_file_name in specified_file_names:
                        filtered_test_files.append(test_file)
                        add_log_entry(f"Including test file: {test_file_str}")
                    else:
                        add_log_entry(f"Excluding test file: {test_file_str} (not in specified list)")
                
                # Replace test_files with the filtered list
                test_files = filtered_test_files
                add_log_entry(f"Using {len(test_files)} test files after filtering")
        
        if not test_files:
            add_log_entry("No test files found in the workspace", level="WARNING")
            result_data["status"] = "skip"
            result_data["tests"]["found"] = 0
            
            # Skip writing results
            return 0
        
        add_log_entry(f"Found {len(test_files)} test files")

        # Skip dependency detection and installation when --run-tests is provided
        add_log_entry("Skipping dependency detection and installation as requested with --run-tests flag")
        
        # Run tests using pytest to properly handle cross-file imports
        test_results = []
        for test_file in test_files:
            add_log_entry(f"Running test file: {test_file.relative_to(repo_workspace)}")
            
            # Use pytest instead of direct Python execution to properly handle imports
            cmd = [sys.executable, "-m", "pytest", str(test_file), "-v"]
            
            try:
                # Set timeout if specified
                timeout = args.timeout if hasattr(args, 'timeout') else None
                
                # Set up environment to add repo workspace to PYTHONPATH
                env = os.environ.copy()
                env["PYTHONPATH"] = str(repo_workspace) + os.pathsep + env.get("PYTHONPATH", "")
                
                add_log_entry(f"Running with PYTHONPATH: {env['PYTHONPATH']}")
                
                # Set up enhanced environment to ensure proper module imports
                env = os.environ.copy()
                
                # Construct a better PYTHONPATH that includes:
                # 1. The repository root (for imports relative to the repo root)
                # 2. The current directory (for local imports)
                pythonpaths = [str(repo_workspace), "."]
                
                # Combine the paths and add any existing PYTHONPATH
                pythonpath_value = os.pathsep.join(pythonpaths)
                if "PYTHONPATH" in env and env["PYTHONPATH"]:
                    pythonpath_value += os.pathsep + env["PYTHONPATH"]
                
                env["PYTHONPATH"] = pythonpath_value
                
                add_log_entry(f"Running with PYTHONPATH: {env['PYTHONPATH']}")
                
                # Run the test with subprocess and configured environment
                result = subprocess.run(
                    cmd,
                    cwd=repo_workspace,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=env
                )
                
                # Determine status based on test results
                test_file_status = "success" if result.returncode == 0 else "failure"
                
                # Store the result
                test_results.append({
                    "name": str(test_file.relative_to(repo_workspace)),
                    "status": test_file_status,
                    "message": result.stdout + "\n" + result.stderr,
                    "returncode": result.returncode
                })
                
                add_log_entry(f"Test {test_file.relative_to(repo_workspace)} completed with status: {test_file_status}")
                
                # Display detailed test output if verbose and test failed
                if args.verbose and test_file_status == "failure":
                    add_log_entry(f"Test failure details for {test_file.relative_to(repo_workspace)}:", level="ERROR")
                    # Print a reasonable amount of the error message, capped to avoid overwhelming output
                    error_lines = (result.stdout + "\n" + result.stderr).split("\n")
                    
                    # Always print the actual command output for debugging
                    logger.error("Test command output:")
                    for line in error_lines:
                        logger.error(f"  {line}")
                    
                    # Focus on showing the actual error part rather than the full output
                    error_excerpt = []
                    # Find error sections in the output - look for Traceback or FAILED
                    error_section_found = False
                    for line in error_lines:
                        if "Traceback" in line or "FAILED" in line or "Error" in line or "ImportError" in line:
                            error_section_found = True
                        if error_section_found:
                            error_excerpt.append(line)
                    
                    # If we found an error section, print it (up to 50 lines)
                    if error_excerpt:
                        logger.error("Error details:")
                        for line in error_excerpt:
                            logger.error(f"  {line}")
                    # If no specific error section found, print the last part of the output
                    else:
                        logger.error("Last lines of output:")
                        for line in error_lines[-min(30, len(error_lines)):]:
                            logger.error(f"  {line}")
            except subprocess.TimeoutExpired:
                add_log_entry(f"Test {test_file.relative_to(repo_workspace)} timed out after {timeout} seconds", level="WARNING")
                test_results.append({
                    "name": str(test_file.relative_to(repo_workspace)),
                    "status": "failure",
                    "message": f"Test timed out after {timeout} seconds",
                    "returncode": -1
                })
            except Exception as e:
                add_log_entry(f"Error running test {test_file.relative_to(repo_workspace)}: {str(e)}", level="ERROR")
                test_results.append({
                    "name": str(test_file.relative_to(repo_workspace)),
                    "status": "error",
                    "message": str(e),
                    "returncode": -1
                })
        
        # Calculate result statistics
        total_tests = len(test_results)
        passed_tests = sum(1 for r in test_results if r["status"] == "success")
        failed_tests = sum(1 for r in test_results if r["status"] == "failure")
        error_tests = sum(1 for r in test_results if r["status"] == "error")
        
        result_data["tests"]["found"] = total_tests
        result_data["tests"]["passed"] = passed_tests
        result_data["tests"]["failed"] = failed_tests + error_tests
        result_data["tests"]["skipped"] = 0
        result_data["tests"]["details"] = test_results
        
        # Extract individual tests from test outputs
        individual_tests = []
        
        # Create a dictionary to track tests by file
        tests_by_file = {}
        
        for test_file_result in test_results:
            test_file_path = test_file_result["name"]
            test_output = test_file_result.get("message", "")
            
            # Initialize tests array for this file
            if test_file_path not in tests_by_file:
                tests_by_file[test_file_path] = []
            
            # Parse pytest output to find individual test results
            # Look for lines like "test_function PASSED" or "test_function FAILED"
            for line in test_output.split('\n'):
                if ' PASSED ' in line or ' FAILED ' in line or ' SKIPPED ' in line or ' ERROR ' in line:
                    try:
                        # Extract test name
                        parts = line.split(' ', 1)[0].strip()
                        if '::' in parts:
                            file_name, test_name = parts.split('::', 1)
                        else:
                            test_name = parts
                        
                        # Determine status and message
                        if ' PASSED ' in line:
                            status = "passed"
                            message = ""
                        elif ' FAILED ' in line or ' ERROR ' in line:
                            status = "failed"
                            # Extract failure message from following lines if possible
                            message_lines = []
                            capture_message = False
                            for msg_line in test_output.split('\n'):
                                if capture_message and (' PASSED ' in msg_line or ' FAILED ' in msg_line or ' SKIPPED ' in msg_line):
                                    break
                                if capture_message:
                                    message_lines.append(msg_line)
                                if line in msg_line:  # Found the original failure line
                                    capture_message = True
                            message = "\n".join(message_lines[:10])  # Limit to 10 lines
                        elif ' SKIPPED ' in line:
                            status = "skipped"
                            message = line.split(' SKIPPED ', 1)[1].strip() if ' SKIPPED ' in line else ""
                        else:
                            continue  # Skip if not a recognized status
                        
                        # Create a test object
                        test_object = {
                            "name": test_name,
                            "classname": file_name if 'file_name' in locals() else "",
                            "status": status,
                            "message": message
                        }
                        
                        # Add to tests array for this file
                        tests_by_file[test_file_path].append(test_object)
                        
                        # Add to individual tests list
                        individual_tests.append({
                            "file_path": test_file_path,
                            "name": test_name,
                            "status": status,
                            "message": message
                        })
                    except Exception as e:
                        add_log_entry(f"Error parsing individual test from line: {line}, error: {str(e)}", level="WARNING")
        
        # Add individual tests to result data
        if individual_tests:
            result_data["individual_tests"] = individual_tests
            add_log_entry(f"Extracted {len(individual_tests)} individual tests from pytest output")
        
        # Update test files with tests array
        for i, test_file in enumerate(test_results):
            file_path = test_file["name"]
            if file_path in tests_by_file:
                # Add the tests array to the test file result
                test_results[i]["tests"] = tests_by_file[file_path]
                
                # Update test file status based on test results
                tests = tests_by_file[file_path]
                passed_count = sum(1 for t in tests if t.get("status") == "passed")
                failed_count = sum(1 for t in tests if t.get("status") == "failed")
                skipped_count = sum(1 for t in tests if t.get("status") == "skipped")
                
                # Update test file status based on actual test results
                if len(tests) == 0:
                    test_results[i]["status"] = "skipped"
                elif failed_count > 0 and passed_count == 0:
                    test_results[i]["status"] = "failure"
                elif failed_count > 0 and passed_count > 0:
                    test_results[i]["status"] = "partial_success"
                elif passed_count > 0:
                    test_results[i]["status"] = "success"
                else:
                    test_results[i]["status"] = "skipped"
                
                add_log_entry(f"File {file_path}: {passed_count} passed, {failed_count} failed, {skipped_count} skipped, status: {test_results[i]['status']}")
        
        # Create a proper test_files array for the final result
        result_test_files = []
        for test_file in test_results:
            file_path = test_file["name"]
            # Create entry for each test file with all needed properties
            test_file_entry = {
                "path": file_path,
                "status": test_file["status"],
                "tested_files": [],  # Empty array as per existing format
                "tests": test_file.get("tests", [])
            }
            
            # Add the summary field with test counts
            tests = test_file_entry["tests"]
            test_file_entry["summary"] = {
                "passed_tests": sum(1 for t in tests if t.get("status") == "passed"),
                "failed_tests": sum(1 for t in tests if t.get("status") in ["failure", "error"]),
                "skipped_tests": sum(1 for t in tests if t.get("status") == "skipped")
            }
            
            result_test_files.append(test_file_entry)
            
        # Add the test_files to the result_data
        result_data["test_files"] = result_test_files
        add_log_entry(f"Added {len(result_test_files)} test files to result with test lists")
        
        # Set overall status
        if passed_tests == total_tests:
            result_data["status"] = "success"
            add_log_entry(f"All {passed_tests} tests passed")
        elif passed_tests > 0:
            result_data["status"] = "partial_success"
            add_log_entry(f"{passed_tests} tests passed, {failed_tests + error_tests} tests failed")
        else:
            result_data["status"] = "failure"
            add_log_entry(f"All {failed_tests + error_tests} tests failed")
            
            # In verbose mode, print a summary of the failures
            if args.verbose:
                add_log_entry("=== TEST FAILURE SUMMARY ===", level="ERROR")
                for i, test_result in enumerate(test_results):
                    if test_result["status"] != "success":
                        add_log_entry(f"Test #{i+1}: {test_result['name']} - {test_result['status']}", level="ERROR")
                        
                        # Extract the key error message if possible
                        message = test_result["message"]
                        error_lines = message.split("\n")
                        error_extract = ""
                        
                        # Look for common error indicators
                        for line in error_lines:
                            if "ImportError:" in line or "ModuleNotFoundError:" in line or "AssertionError:" in line:
                                error_extract = line.strip()
                                break
                        
                        if error_extract:
                            add_log_entry(f"  Error: {error_extract}", level="ERROR")
                        else:
                            # If no specific error found, provide a general note
                            add_log_entry(f"  See detailed logs for error information", level="ERROR")
                
                add_log_entry("=== END OF FAILURE SUMMARY ===", level="ERROR")
        
        # Generate summary
        end_time = time.time()
        elapsed_time = end_time - start_time
        
        # Update result data with summary information
        result_data["execution"]["elapsed_time"] = elapsed_time
        
        add_log_entry(f"Process completed in {elapsed_time:.2f} seconds")
        
        # Write the final result to test_results.jsonl
        with open(test_results_jsonl_path, "a") as f:
            f.write(json.dumps(result_data) + "\n")
        
        add_log_entry(f"Results written to {test_results_jsonl_path}")
        
        return 0
    
    except Exception as e:
        error_message = str(e)
        add_log_entry(f"An error occurred: {error_message}", level="ERROR", exc_info=True)
        
        # Update result data with error information
        result_data["status"] = "error"
        result_data["error"] = error_message
        
        # Write the error result to test_results.jsonl
        with open(test_results_jsonl_path, "a") as f:
            f.write(json.dumps(result_data) + "\n")
        
        return 1
    
    finally:
        # Clean up the workspace directory to save disk space
        try:
            if repo_workspace and repo_workspace.exists():
                add_log_entry(f"Cleaning up workspace directory: {repo_workspace}")
                shutil.rmtree(repo_workspace)
        except Exception as e:
            add_log_entry(f"Warning: Failed to clean up workspace directory: {e}", level="WARNING")


def run_tests_from_jsonl(args: argparse.Namespace) -> int:
    """
    Run tests from previously extracted test.jsonl file without creating virtual environments.
    Tests will be run using pytest with the system Python interpreter directly in the repository directories
    where the tests were originally located.
    
    Args:
        args: Command line arguments
    
    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
    # Configure logging
    logger = configure_process_logging(args.verbose)
    
    # Verify output directory and test.jsonl exist
    output_dir = Path(args.output_dir)
    if not output_dir.exists():
        logger.error(f"Output directory {output_dir} does not exist")
        return 1
    
    test_jsonl_path = output_dir / "test.jsonl"
    if not test_jsonl_path.exists():
        logger.error(f"Test file {test_jsonl_path} does not exist. Run --extract-tests first.")
        return 1
    
    # Create or clear test_results.jsonl file
    test_results_jsonl_path = output_dir / "test_results.jsonl"
    if test_results_jsonl_path.exists():
        logger.info(f"Clearing existing test results file: {test_results_jsonl_path}")
        with open(test_results_jsonl_path, 'w') as f:
            pass
    
    # Track repositories with their test data
    repositories_data = []
    
    # Read repositories from test.jsonl
    logger.info(f"Reading test data from {test_jsonl_path}")
    with open(test_jsonl_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    record = json.loads(line)
                    repositories_data.append(record)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse line in test.jsonl: {e}")
    
    logger.info(f"Found {len(repositories_data)} repositories with test data")
    
    # Check if there are no repositories found
    if len(repositories_data) == 0:
        logger.info("No repositories found in test.jsonl")
        return 1
    
    # Set require_tested_files flag
    if hasattr(args, 'require_tested_files') and args.require_tested_files:
        logger.info("Require tested_files mode is enabled - will skip test files without tested_files information")
    
        # Filter repositories to only include those with valid test files
        filtered_repositories_data = []
        for repo_data in repositories_data:
            repo_identifier = repo_data.get("repository", "")
            tests = repo_data.get("tests", [])
            
            # Filter tests to only include those with non-empty tested_files
            valid_tests = [test for test in tests if test.get("tested_files")]
            
            if valid_tests:
                # Update the repo data with only valid tests
                filtered_repo_data = repo_data.copy()
                filtered_repo_data["tests"] = valid_tests
                filtered_repositories_data.append(filtered_repo_data)
                logger.info(f"Repository {repo_identifier}: Kept {len(valid_tests)} out of {len(tests)} test files with tested_files information")
            else:
                logger.info(f"Repository {repo_identifier}: Skipped - no test files with tested_files information")
        
        # Update repositories_data with filtered data
        skipped_count = len(repositories_data) - len(filtered_repositories_data)
        logger.info(f"Filtered out {skipped_count} repositories with no valid test files")
        repositories_data = filtered_repositories_data
        
        if not repositories_data:
            logger.info("No repositories with valid test files (containing tested_files information) found")
            return 0
    
    # Convert repository data to paths for run_tests_parallel
    repositories = []
    repo_test_info = {}  # Store test info by repository path for later use
    
    for repo_data in repositories_data:
        repo_identifier = repo_data.get("repository", "")
        if repo_identifier:
            # For local paths, we need to check if they exist
            repo_path = Path(repo_identifier)
            if repo_path.exists():
                tests_info = repo_data.get("tests", [])
                if tests_info:
                    # Validate test file paths
                    valid_test_files = []
                    for test_info in tests_info:
                        if "path" in test_info:
                            test_path = test_info.get("path")
                            # Make a copy of the test info to modify
                            processed_test_info = test_info.copy()
                            
                            # Get tested_files field
                            tested_files = processed_test_info.get("tested_files", [])
                            
                            # Skip test files without tested_files if require_tested_files is enabled
                            if args.require_tested_files and not tested_files:
                                logger.debug(f"Skipping test file without tested_files: {test_path}")
                                continue
                            
                            # Check if the test file exists
                            full_path = repo_path / test_path
                            if full_path.exists():
                                valid_test_files.append(processed_test_info)
                                logger.debug(f"Test file found: {test_path} with {len(tested_files)} tested files")
                            else:
                                logger.warning(f"Test file not found: {test_path} in repository {repo_identifier}")
                        else:
                            logger.warning(f"Test info missing path in repository {repo_identifier}")
                    
                    if valid_test_files:
                        # Only add repository if it has valid test files after filtering
                        repositories.append(repo_path)
                        repo_test_info[str(repo_path)] = valid_test_files
                        logger.info(f"Found {len(valid_test_files)} valid test files for repository {repo_identifier}")
                    else:
                        logger.warning(f"No valid test files found for repository {repo_identifier}")
                else:
                    logger.warning(f"No test files defined for repository {repo_identifier}")
            else:
                logger.warning(f"Repository directory {repo_path} does not exist. Skipping.")
    
    if not repositories:
        logger.error("No valid repository paths found in test.jsonl. Exiting.")
        return 1
    
    logger.info(f"Running tests for {len(repositories)} repositories in parallel")
    
    # Use the current Python environment (no virtual environment)
    unified_venv = None
    
    # Run tests in parallel using run_tests_parallel
    test_results = run_tests_parallel(repositories, output_dir, unified_venv, args, repo_test_info)
    
    # Process the results to include test file details and tested files
    enhanced_results = []
    
    for result in test_results:
        # Skip processing if this was a timeout or error result
        if result.get("status") == "error" and "timeout" in result.get("error", "").lower():
            # Just add the timeout result directly
            enhanced_results.append(result)
            continue
        
        # Create a mapping of test files and their tests
        test_file_mapping = {}
        repo_path = result['repository']
        
        # Get test file info from repo_test_info if available
        repo_test_files = repo_test_info.get(repo_path, [])
        test_file_to_tested_files = {
            test_info['path']: {
                'path': test_info['path'],
                'tested_files': test_info.get('tested_files', []),
                'status': 'skipped',  # Default all files to skipped initially
                'tests': [],
                'summary': {'passed_tests': 0, 'failed_tests': 0, 'skipped_tests': 0}
            }
            for test_info in repo_test_files
        }
        
        # Get all tests from the pytest details
        all_tests = []
        for detail in result['tests']['details']:
            if detail['name'] == 'pytest':
                all_tests = detail['tests']
                break
        
        # If no tests were run and status is skipped, just add all files as skipped
        if result['status'] == 'skipped' and not all_tests:
            test_file_mapping = test_file_to_tested_files
        else:
            # Group tests by their test files
            for test in all_tests:
                # Try to match test to original file path
                test_file = None
                test_module = None
                
                # First try to extract from classname
                if test['classname']:
                    parts = test['classname'].split('.')
                    if len(parts) >= 2:
                        test_module = '/'.join(parts[:-1])
                        potential_path = f"{test_module}.py"
                        if any(info['path'].endswith(potential_path) for info in repo_test_files):
                            test_file = next(info['path'] for info in repo_test_files if info['path'].endswith(potential_path))
                
                # If no match from classname, try test name
                if not test_file and test['name']:
                    parts = test['name'].split('.')
                    if len(parts) >= 2:
                        test_module = '/'.join(parts[:-1])
                        potential_paths = [
                            f"{test_module}.py",
                            f"{parts[0]}/{parts[1]}.py",
                            f"{parts[0]}/test_{parts[1]}.py"
                        ]
                        for path in potential_paths:
                            if any(info['path'].endswith(path) for info in repo_test_files):
                                test_file = next(info['path'] for info in repo_test_files if info['path'].endswith(path))
                                break
                
                # If still no match, try direct path matching
                if not test_file:
                    for info in repo_test_files:
                        file_name = info['path'].split('/')[-1]
                        if (test['name'] in file_name or 
                            (test['classname'] and test['classname'].split('.')[-1] in file_name)):
                            test_file = info['path']
                            break
                
                # If we found a matching file, add the test to it
                if test_file:
                    if test_file not in test_file_mapping:
                        test_file_mapping[test_file] = test_file_to_tested_files.get(test_file, {
                            'path': test_file,
                            'tested_files': [],
                            'status': 'success',  # Only set to success when we have tests
                            'tests': [],
                            'summary': {'passed_tests': 0, 'failed_tests': 0, 'skipped_tests': 0}
                        })
                    
                    # Add test to the file's tests
                    test_file_mapping[test_file]['tests'].append(test)
                    
                    # Update summary based on test status
                    if test['status'] == 'passed':
                        test_file_mapping[test_file]['summary']['passed_tests'] += 1
                    elif test['status'] in ['failure', 'error']:
                        test_file_mapping[test_file]['summary']['failed_tests'] += 1
                    elif test['status'] == 'skipped':
                        test_file_mapping[test_file]['summary']['skipped_tests'] += 1
                else:
                    # If we couldn't match to a file, create a fallback entry
                    fallback_path = f"{test_module}.py" if test_module else "unknown_test.py"
                    if fallback_path not in test_file_mapping:
                        test_file_mapping[fallback_path] = {
                            'path': fallback_path,
                            'tested_files': [],
                            'status': 'success',
                            'tests': [],
                            'summary': {'passed_tests': 0, 'failed_tests': 0, 'skipped_tests': 0}
                        }
                    test_file_mapping[fallback_path]['tests'].append(test)
        
        # Add any test files that didn't have any tests run
        for test_info in repo_test_files:
            if test_info['path'] not in test_file_mapping:
                test_file_mapping[test_info['path']] = {
                    'path': test_info['path'],
                    'tested_files': test_info.get('tested_files', []),
                    'status': 'skipped',
                    'tests': [],
                    'summary': {'passed_tests': 0, 'failed_tests': 0, 'skipped_tests': 0}
                }
        
        # Recalculate status for each test file based on its test results
        for test_file in test_file_mapping.values():
            passed_count = test_file['summary']['passed_tests']
            failed_count = test_file['summary']['failed_tests']
            skipped_count = test_file['summary']['skipped_tests']
            total_tests = passed_count + failed_count + skipped_count
            
            if total_tests == 0:
                test_file['status'] = 'skipped'
            elif failed_count > 0 and passed_count == 0:
                test_file['status'] = 'failure'
            elif failed_count > 0 and passed_count > 0:
                test_file['status'] = 'partial_success'
            elif passed_count > 0:
                test_file['status'] = 'success'
            else:
                test_file['status'] = 'skipped'
            
            logger.debug(f"Test file {test_file['path']}: {passed_count} passed, {failed_count} failed, {skipped_count} skipped -> {test_file['status']}")
        
        # Calculate total summary
        total_summary = {
            'total_files': len(test_file_mapping),
            'passed_files': sum(1 for f in test_file_mapping.values() if f['status'] == 'success'),
            'partial_files': sum(1 for f in test_file_mapping.values() if f['status'] == 'partial_success'),
            'failed_files': sum(1 for f in test_file_mapping.values() if f['status'] == 'failure'),
            'passed_tests': sum(f['summary']['passed_tests'] for f in test_file_mapping.values()),
            'failed_tests': sum(f['summary']['failed_tests'] for f in test_file_mapping.values()),
            'skipped_tests': sum(f['summary']['skipped_tests'] for f in test_file_mapping.values())
        }
        
        # Create enhanced result
        enhanced_result = {
            'repository': result['repository'],
            'status': result['status'],
            'test_files': list(test_file_mapping.values()),
            'total_summary': total_summary,
            'execution_time': result['execution']['elapsed_time']
        }
        
        # Update overall repository status based on test file statuses
        if all(f['status'] == 'success' for f in test_file_mapping.values()):
            enhanced_result['status'] = 'success'
        elif all(f['status'] == 'skipped' for f in test_file_mapping.values()):
            enhanced_result['status'] = 'skip'
        elif any(f['status'] in ['success', 'partial_success'] for f in test_file_mapping.values()):
            enhanced_result['status'] = 'partial_success'
        else:
            enhanced_result['status'] = 'failure'
        
        enhanced_results.append(enhanced_result)
        
        # Write the enhanced result to the output file
        with open(test_results_jsonl_path, "a") as f:
            f.write(json.dumps(enhanced_result) + "\n")
    
    # Count successful and failed repositories
    success_count = 0
    failure_count = 0
    
    for result in enhanced_results:
        status = result.get("status", "")
        if status == "success" or status == "skip":
            success_count += 1
        else:
            failure_count += 1
    
    logger.info(f"Test execution complete: {success_count} repositories succeeded/skipped, {failure_count} repositories failed")
    
    # Return success if all repositories passed or were skipped
    return 1 if failure_count > 0 else 0


def _process_test_repo_wrapper(args_and_repo):
    """Helper function to process a single test repository in multiprocessing.
    
    Args:
        args_and_repo (tuple): Tuple containing (args, repo_data, workspace_dir, index)
        
    Returns:
        int: Exit code from process_test_repo
    """
    args, repo_data, workspace_dir, index = args_and_repo
    # Clone args to avoid modifying the original
    args_copy = argparse.Namespace(**vars(args))
    # Mark this args object as coming from a pool
    args_copy._is_from_pool = True
    
    logger = configure_process_logging(args_copy.verbose)
    
    # Set up process timeout - this ensures the process doesn't run forever
    start_time = time.time()
    def timeout_checker():
        while True:
            if time.time() - start_time > args_copy.timeout:
                logger.error(f"Process exceeded timeout of {args_copy.timeout} seconds")
                os._exit(1)  # Force exit this process
            time.sleep(1)  # Check more frequently
    
    # Start timeout checker in a separate thread
    timeout_thread = threading.Thread(target=timeout_checker, daemon=True)
    timeout_thread.start()
    
    # Create a hard timer to terminate process after timeout
    def hard_timeout_handler():
        logger.error(f"Process hard timeout after {args_copy.timeout} seconds")
        os._exit(1)
    
    timer = threading.Timer(args_copy.timeout, hard_timeout_handler)
    timer.daemon = True
    timer.start()
    
    return process_test_repo(args_copy, repo_data, workspace_dir, index)


def _process_repo_wrapper(args_and_repo):
    """Helper function to process a single repository in multiprocessing.
    
    Args:
        args_and_repo (tuple): Tuple containing (args, repo_info)
        
    Returns:
        int: Exit code from process_single_repo
    """
    args, repo_info = args_and_repo
    # Clone args to avoid modifying the original
    args_copy = argparse.Namespace(**vars(args))
    # Mark this args object as coming from a pool
    args_copy._is_from_pool = True
    
    logger = configure_process_logging(args_copy.verbose)
    
    # Set up process timeout - this ensures the process doesn't run forever
    start_time = time.time()
    def timeout_checker():
        while True:
            if time.time() - start_time > args_copy.timeout:
                logger.error(f"Process exceeded timeout of {args_copy.timeout} seconds")
                os._exit(1)  # Force exit this process
            time.sleep(1)  # Check more frequently
    
    # Start timeout checker in a separate thread
    timeout_thread = threading.Thread(target=timeout_checker, daemon=True)
    timeout_thread.start()
    
    # Create a hard timer to terminate process after timeout
    def hard_timeout_handler():
        logger.error(f"Process hard timeout after {args_copy.timeout} seconds")
        os._exit(1)
    
    timer = threading.Timer(args_copy.timeout, hard_timeout_handler)
    timer.daemon = True
    timer.start()
    
    return process_single_repo(args_copy, repo_info, None)


def _process_local_wrapper(args_and_path):
    """Helper function to process a single local directory in multiprocessing.
    
    Args:
        args_and_path (tuple): Tuple containing (args, local_path)
        
    Returns:
        int: Exit code from process_single_repo
    """
    args, local_path = args_and_path
    # Clone args to avoid modifying the original
    args_copy = argparse.Namespace(**vars(args))
    # Mark this args object as coming from a pool
    args_copy._is_from_pool = True
    
    logger = configure_process_logging(args_copy.verbose)
    
    # Set up process timeout - this ensures the process doesn't run forever
    start_time = time.time()
    def timeout_checker():
        while True:
            if time.time() - start_time > args_copy.timeout:
                logger.error(f"Process exceeded timeout of {args_copy.timeout} seconds")
                os._exit(1)  # Force exit this process
            time.sleep(1)  # Check more frequently
    
    # Start timeout checker in a separate thread
    timeout_thread = threading.Thread(target=timeout_checker, daemon=True)
    timeout_thread.start()
    
    # Create a hard timer to terminate process after timeout
    def hard_timeout_handler():
        logger.error(f"Process hard timeout after {args_copy.timeout} seconds")
        os._exit(1)
    
    timer = threading.Timer(args_copy.timeout, hard_timeout_handler)
    timer.daemon = True
    timer.start()
    
    return process_single_repo(args_copy, None, local_path)


def process_repo_list(args: argparse.Namespace) -> int:
    """Process a list of repositories in parallel.
    
    Args:
        args: Command line arguments
    
    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
    # Configure logging for the main process
    logger = configure_process_logging(args.verbose)
    
    # Read and parse the repository list file
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
        return 1
    
    if not repo_infos:
        logger.error("No valid repositories found in the list")
        return 1
    
    # If the output directory exists, get a list of already processed repositories
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results_jsonl_path = output_dir / "results.jsonl"
    
    # If extract_tests is enabled, prepare test.jsonl file
    if args.extract_tests:
        tests_jsonl_path = output_dir / "test.jsonl"
        logger.info(f"Will extract tests to {tests_jsonl_path}")
        
        # For extract-tests we use test.jsonl to check which repos have been processed
        # instead of results.jsonl since we don't write to results.jsonl in this mode
        if args.skip_processed and not args.overwrite and tests_jsonl_path.exists():
            # Get set of processed repository IDs from test.jsonl
            processed_repos = set()
            try:
                with open(tests_jsonl_path, 'r') as f:
                    for line in f:
                        try:
                            record = json.loads(line.strip())
                            if "repository" in record:
                                processed_repos.add(record["repository"])
                        except json.JSONDecodeError:
                            continue
                logger.info(f"Found {len(processed_repos)} already processed repositories in test.jsonl")
                
                # Filter out already processed repositories
                unprocessed_repos = []
                for full_name, sha in repo_infos:
                    repo_id = f"{full_name}@{sha}"
                    if repo_id not in processed_repos:
                        unprocessed_repos.append((full_name, sha))
                
                skipped_count = len(repo_infos) - len(unprocessed_repos)
                logger.info(f"Test extraction: {len(unprocessed_repos)} out of {len(repo_infos)} repositories (skipping {skipped_count} already processed)")
                repo_infos = unprocessed_repos
            except Exception as e:
                logger.warning(f"Error reading test.jsonl: {e}")
    elif args.skip_processed and not args.overwrite and results_jsonl_path.exists():
        # Standard approach - use results.jsonl for non-extract-tests mode
        # Get set of processed repository IDs
        processed_repos = get_processed_repos(results_jsonl_path)
        logger.info(f"Found {len(processed_repos)} already processed repositories")
        
        # Filter out already processed repositories
        unprocessed_repos = []
        for full_name, sha in repo_infos:
            repo_id = f"{full_name}@{sha}"
            if repo_id not in processed_repos:
                unprocessed_repos.append((full_name, sha))
        
        skipped_count = len(repo_infos) - len(unprocessed_repos)
        mode_desc = "test extraction" if args.extract_tests else "processing"
        logger.info(f"{mode_desc.capitalize()} {len(unprocessed_repos)} out of {len(repo_infos)} repositories (skipping {skipped_count} already processed)")
        repo_infos = unprocessed_repos
    
    if not repo_infos:
        logger.info("All repositories have already been processed")
        return 0
    
    # Create argument tuples for the wrapper function
    arg_tuples = [(args, repo_info) for repo_info in repo_infos]
    
    # Create a pool of worker processes
    all_test_records = []  # Store all test records to write at the end
    with multiprocessing.Pool(processes=args.num_workers) as pool:
        # Process repositories in parallel with progress bar
        action = "Extracting tests from" if args.extract_tests else "Processing"
        pbar = tqdm(total=len(repo_infos), desc=f"{action} repositories", unit="repo")
        results = []
        
        # Use imap_unordered for better real-time progress updates
        for result in pool.imap_unordered(_process_test_repo_wrapper, arg_tuples):
            if args.extract_tests and isinstance(result, tuple):
                exit_code, test_record = result
                results.append(exit_code)
                if test_record:
                    all_test_records.append(test_record)
            else:
                results.append(result)
            pbar.update(1)
        
        pbar.close()
    
    # If extract_tests is enabled, write all collected test records to test.jsonl at once
    if args.extract_tests and all_test_records:
        logger.info(f"Writing {len(all_test_records)} test records to {tests_jsonl_path}")
        try:
            # Make sure the output directory exists
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Create test.jsonl file with all records
            with open(tests_jsonl_path, "w") as f:
                for record in all_test_records:
                    f.write(json.dumps(record) + "\n")
            
            logger.info(f"Successfully wrote all test records to {tests_jsonl_path}")
        except Exception as e:
            logger.error(f"Error writing to test.jsonl: {e}")
            return 1
    
    # Check if any process failed
    return 1 if any(result != 0 for result in results) else 0

# Add a new wrapper function to collect test data during multiprocessing without writing to file
def _process_repo_wrapper_collect_tests(args_and_repo):
    """Helper function to process a single repository in multiprocessing and collect test data.
    
    Args:
        args_and_repo (tuple): Tuple containing (args, repo_info)
        
    Returns:
        tuple: (exit_code, test_record) where test_record contains the test data
    """
    args, repo_info = args_and_repo
    # Clone args to avoid modifying the original
    args_copy = argparse.Namespace(**vars(args))
    # Mark this args object as coming from a pool
    args_copy._is_from_pool = True
    # Set a flag to indicate we're collecting tests
    args_copy._collect_tests_only = True
    
    logger = configure_process_logging(args_copy.verbose)
    
    # Set up process timeout - this ensures the process doesn't run forever
    start_time = time.time()
    def timeout_checker():
        while True:
            if time.time() - start_time > args_copy.timeout:
                logger.error(f"Process exceeded timeout of {args_copy.timeout} seconds")
                os._exit(1)  # Force exit this process
            time.sleep(1)  # Check more frequently
    
    # Start timeout checker in a separate thread
    timeout_thread = threading.Thread(target=timeout_checker, daemon=True)
    timeout_thread.start()
    
    # Create a hard timer to terminate process after timeout
    def hard_timeout_handler():
        logger.error(f"Process hard timeout after {args_copy.timeout} seconds")
        os._exit(1)
    
    timer = threading.Timer(args_copy.timeout, hard_timeout_handler)
    timer.daemon = True
    timer.start()
    
    try:
        return_code = process_single_repo(args_copy, repo_info, None)
        # Return the exit code and the test record if available
        return return_code, getattr(args_copy, '_test_record', None)
    except Exception as e:
        logger.error(f"Error in _process_repo_wrapper_collect_tests: {e}")
        return 1, None


def process_local_list(args: argparse.Namespace) -> int:
    """Process a list of local directories in parallel.
    
    Args:
        args: Command line arguments
    
    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
    # Configure logging for the main process
    logger = configure_process_logging(args.verbose)
    
    # Read the local directory list file
    with open(args.local_list, 'r') as f:
        dir_lines = f.readlines()
    
    # Parse directory paths
    dir_paths = []
    for line in dir_lines:
        line = line.strip()
        if line and not line.startswith('#'):
            dir_paths.append(line)
    
    if not dir_paths:
        logger.error("No valid directories found in the list")
        return 1
    
    # If the output directory exists, get a list of already processed repositories
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results_jsonl_path = output_dir / "results.jsonl"
    
    # If extract_tests is enabled, prepare test.jsonl file
    if args.extract_tests:
        tests_jsonl_path = output_dir / "test.jsonl"
        logger.info(f"Will extract tests to {tests_jsonl_path}")
        
        # For extract-tests we use test.jsonl to check which repos have been processed
        # instead of results.jsonl since we don't write to results.jsonl in this mode
        if args.skip_processed and not args.overwrite and tests_jsonl_path.exists():
            # Get set of processed repository IDs from test.jsonl
            processed_repos = set()
            try:
                with open(tests_jsonl_path, 'r') as f:
                    for line in f:
                        try:
                            record = json.loads(line.strip())
                            if "repository" in record:
                                processed_repos.add(record["repository"])
                        except json.JSONDecodeError:
                            continue
                logger.info(f"Found {len(processed_repos)} already processed repositories in test.jsonl")
                
                # Filter out already processed repositories
                filtered_dir_paths = []
                for dir_path in dir_paths:
                    repo_identifier = str(Path(dir_path).absolute())
                    if repo_identifier not in processed_repos:
                        filtered_dir_paths.append(dir_path)
                    else:
                        logger.info(f"Skipping already processed directory: {repo_identifier}")
                
                logger.info(f"Test extraction: {len(filtered_dir_paths)} out of {len(dir_paths)} directories (skipping {len(dir_paths) - len(filtered_dir_paths)} already processed)")
                dir_paths = filtered_dir_paths
            except Exception as e:
                logger.warning(f"Error reading test.jsonl: {e}")
    elif args.skip_processed and not args.overwrite and results_jsonl_path.exists():
        processed_repos = get_processed_repos(results_jsonl_path)
        logger.info(f"Found {len(processed_repos)} already processed repositories")
        
        # Filter out already processed repositories
        filtered_dir_paths = []
        for dir_path in dir_paths:
            repo_identifier = str(Path(dir_path).absolute())
            if repo_identifier not in processed_repos:
                filtered_dir_paths.append(dir_path)
            else:
                logger.info(f"Skipping already processed directory: {repo_identifier}")
        
        mode_desc = "test extraction" if args.extract_tests else "processing"
        logger.info(f"{mode_desc.capitalize()} {len(filtered_dir_paths)} out of {len(dir_paths)} directories (skipping {len(dir_paths) - len(filtered_dir_paths)} already processed)")
        dir_paths = filtered_dir_paths
    
    if not dir_paths:
        logger.info("All directories have already been processed")
        return 0
    
    # Create argument tuples for the wrapper function
    arg_tuples = [(args, dir_path) for dir_path in dir_paths]
    
    # Create a pool of worker processes
    all_test_records = []  # Store all test records to write at the end
    with multiprocessing.Pool(processes=args.num_workers) as pool:
        # Process directories in parallel with progress bar
        action = "Extracting tests from" if args.extract_tests else "Processing"
        pbar = tqdm(total=len(dir_paths), desc=f"{action} directories", unit="dir")
        results = []
        
        # Use imap_unordered for better real-time progress updates
        for result in pool.imap_unordered(_process_local_wrapper_collect_tests if args.extract_tests else _process_local_wrapper, arg_tuples):
            if args.extract_tests and isinstance(result, tuple):
                exit_code, test_record = result
                results.append(exit_code)
                if test_record:
                    all_test_records.append(test_record)
            else:
                results.append(result)
            pbar.update(1)
        
        pbar.close()
    
    # If extract_tests is enabled, write all collected test records to test.jsonl at once
    if args.extract_tests and all_test_records:
        logger.info(f"Writing {len(all_test_records)} test records to {tests_jsonl_path}")
        try:
            # Make sure the output directory exists
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Create test.jsonl file with all records
            with open(tests_jsonl_path, "w") as f:
                for record in all_test_records:
                    f.write(json.dumps(record) + "\n")
            
            logger.info(f"Successfully wrote all test records to {tests_jsonl_path}")
        except Exception as e:
            logger.error(f"Error writing to test.jsonl: {e}")
            return 1
    
    # Check if any process failed
    return 1 if any(result != 0 for result in results) else 0

# Add a new wrapper function to collect test data during multiprocessing without writing to file
def _process_local_wrapper_collect_tests(args_and_path):
    """Helper function to process a single local directory in multiprocessing and collect test data.
    
    Args:
        args_and_path (tuple): Tuple containing (args, local_path)
        
    Returns:
        tuple: (exit_code, test_record) where test_record contains the test data
    """
    args, local_path = args_and_path
    # Clone args to avoid modifying the original
    args_copy = argparse.Namespace(**vars(args))
    # Mark this args object as coming from a pool
    args_copy._is_from_pool = True
    # Set a flag to indicate we're collecting tests
    args_copy._collect_tests_only = True
    
    logger = configure_process_logging(args_copy.verbose)
    
    # Set up process timeout - this ensures the process doesn't run forever
    start_time = time.time()
    def timeout_checker():
        while True:
            if time.time() - start_time > args_copy.timeout:
                logger.error(f"Process exceeded timeout of {args_copy.timeout} seconds")
                os._exit(1)  # Force exit this process
            time.sleep(1)  # Check more frequently
    
    # Start timeout checker in a separate thread
    timeout_thread = threading.Thread(target=timeout_checker, daemon=True)
    timeout_thread.start()
    
    # Create a hard timer to terminate process after timeout
    def hard_timeout_handler():
        logger.error(f"Process hard timeout after {args_copy.timeout} seconds")
        os._exit(1)
    
    timer = threading.Timer(args_copy.timeout, hard_timeout_handler)
    timer.daemon = True
    timer.start()
    
    try:
        return_code = process_single_repo(args_copy, None, local_path)
        # Return the exit code and the test record if available
        return return_code, getattr(args_copy, '_test_record', None)
    except Exception as e:
        logger.error(f"Error in _process_local_wrapper_collect_tests: {e}")
        return 1, None


def main():
    """Main entry point for the program."""
    try:
        args = parse_arguments()
        
        # Configure logging for the main process
        logger = configure_process_logging(args.verbose)
        
        if args.run_tests:
            # Direct mode for running tests from test.jsonl without dependency setup
            logger.info("Running tests directly from test.jsonl using current Python environment")
            return run_tests_from_jsonl(args)
        elif args.global_mode:
            # Run in unified pipeline mode (global environment)
            return run_unified_pipeline(args)
        else:
            # Based on the source argument, dispatch to the appropriate function
            if args.repo:
                # Process a single repository
                full_name, sha = args.repo
                return process_single_repo(args, repo_info=(full_name, sha))
            elif args.local:
                # Process a local directory
                return process_single_repo(args, local_path=args.local)
            elif args.repo_list:
                # Process multiple repositories from a list
                return process_repo_list(args)
            elif args.local_list:
                # Process multiple local directories from a list
                return process_local_list(args)
            else:
                # This shouldn't happen due to the required argument group
                logger.error("No valid operation specified")
                return 1
    except KeyboardInterrupt:
        print("\nOperation interrupted by user")
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    # Clean up any dangling Docker images
    try:
        subprocess.run(
            'docker rmi $(docker images --filter "dangling=true" -q) > /dev/null 2>&1',
            shell=True, check=False
        )
    except Exception as e:
        logger = configure_process_logging(True)  # Use verbose for error logging
        logger.error("Failed to clean up dangling Docker images: %s", str(e))
    
    sys.exit(main()) 