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

Options:
    --repo FULL_NAME SHA    The full name of the repository (e.g., user/repo) and SHA
    --local PATH            Local folder path to process
    --repo-list FILE       Text file containing list of repositories (format: user/repo sha)
    --local-list FILE      Text file containing list of local directories
    --global               Use the unified global pipeline (single environment for all repositories)
    --output-dir DIR       Directory to store output files (default: output)
    --workspace-dir DIR    Directory to use as workspace (default: temporary directory)
    --timeout SECONDS      Timeout in seconds (default: 7200 - 2 hours). Tests that exceed this time will be forcibly terminated.
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
from typing import List, Tuple, Optional, Dict, Set
from tqdm import tqdm
import re
import threading
import tempfile
import glob

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
        help='Timeout in seconds (default: 7200 - 2 hours). Tests that exceed this time will be forcibly terminated.'
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
    
    return parser.parse_args()


def run_unified_pipeline(args):
    """
    Run the unified global pipeline for multiple repositories.
    
    Args:
        args: Command line arguments
        
    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
    # Configure logging
    logger = configure_process_logging(args.verbose)
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Using output directory: {output_dir}")
    
    try:
        # Load repositories
        repositories = load_repositories(args)
        if not repositories:
            logger.error("No repositories to process. Exiting.")
            return 1
        
        # Apply repository range filter if specified
        total_repos = len(repositories)
        if hasattr(args, 'repo_range') and args.repo_range is not None:
            start_idx, end_idx = args.repo_range
            
            # Validate indices
            if start_idx < 0:
                logger.warning(f"Start index {start_idx} is negative. Using 0 instead.")
                start_idx = 0
            
            if end_idx > total_repos:
                logger.warning(f"End index {end_idx} exceeds the number of repositories ({total_repos}). Using {total_repos} instead.")
                end_idx = total_repos
            
            if start_idx >= end_idx:
                logger.error(f"Invalid range: start index {start_idx} must be less than end index {end_idx}.")
                return 1
            
            # Apply the slice
            repositories = repositories[start_idx:end_idx]
            logger.info(f"Processing repository range [{start_idx}, {end_idx}) - {len(repositories)} repositories out of {total_repos} total")
        else:
            logger.info(f"Processing all {total_repos} repositories")
        
        # Check which stage of the pipeline to run
        # If no specific stage is requested, run the complete pipeline
        run_complete_pipeline = not (args.extract_dep or args.config_venv or args.run_test)
        
        # Step 1: Analyze dependencies across all repositories
        if args.extract_dep or run_complete_pipeline:
            logger.info("\n" + "=" * 40)
            logger.info("🔍 STAGE 1: ANALYZING DEPENDENCIES")
            logger.info("=" * 40)
            
            # Log information about skip-processed state
            if args.skip_processed and args.extract_dep:
                logger.info("Running in extract-dep mode with skip-processed enabled")
                repo_req_jsonl = output_dir / "repo_req.jsonl"
                if repo_req_jsonl.exists():
                    logger.info(f"Will skip repositories already processed in {repo_req_jsonl}")
                else:
                    logger.info(f"No existing processed repositories found at {repo_req_jsonl}")
            
            all_dependencies, repo_req_data = analyze_dependencies_parallel(repositories, output_dir, args)
            
            # In extract-dep mode, we don't save all_dependencies.json as it will be incomplete
            # We'll rebuild it in config-venv stage
            if not args.extract_dep:
                # Save all_dependencies to file for later stages
                deps_path = output_dir / "all_dependencies.json"
                with open(deps_path, 'w') as f:
                    json.dump(list(all_dependencies), f, indent=2)
                logger.info(f"Saved extracted dependencies to {deps_path}")
            else:
                logger.info("Skipping saving all_dependencies.json in extract-dep mode (will be rebuilt in config-venv)")
            
            if args.extract_dep:
                logger.info("Dependency extraction completed. Exiting as requested.")
                return 0
        else:
            # When in config-venv mode, build dependencies from repo_req.jsonl
            if args.config_venv:
                logger.info("\n" + "=" * 40)
                logger.info("🔍 REBUILDING DEPENDENCIES FROM JSONL")
                logger.info("=" * 40)
                
                repo_req_jsonl = output_dir / "repo_req.jsonl"
                if not repo_req_jsonl.exists():
                    logger.error(f"Repository requirements file not found at {repo_req_jsonl}")
                    logger.error("Run with --extract-dep first to generate repository requirements")
                    return 1
                
                all_dependencies = build_dependencies_from_jsonl(output_dir)
                if not all_dependencies:
                    logger.warning("No dependencies found in repo_req.jsonl. The environment might be empty.")
                
                # Save all_dependencies to file for later stages
                deps_path = output_dir / "all_dependencies.json"
                with open(deps_path, 'w') as f:
                    json.dump(list(all_dependencies), f, indent=2)
                logger.info(f"Saved {len(all_dependencies)} rebuilt dependencies to {deps_path}")
            else:
                # For run-test mode, load dependencies from file
                deps_path = output_dir / "all_dependencies.json"
                if not deps_path.exists():
                    logger.error(f"Dependencies file not found at {deps_path}. Run with --extract-dep and --config-venv first.")
                    return 1
                
                try:
                    with open(deps_path, 'r') as f:
                        all_dependencies = set(json.load(f))
                    logger.info(f"Loaded {len(all_dependencies)} dependencies from {deps_path}")
                except Exception as e:
                    logger.error(f"Failed to load dependencies: {e}")
                    return 1
        
        # Step 2: Create unified virtual environment with all dependencies
        if args.config_venv or run_complete_pipeline:
            logger.info("\n" + "=" * 40)
            logger.info("🏗️ STAGE 2: CREATING UNIFIED ENVIRONMENT")
            logger.info("=" * 40)
            unified_venv, install_status = create_unified_environment(all_dependencies, output_dir, args)
            if not unified_venv:
                logger.error("Failed to create unified virtual environment. Exiting.")
                return 1
            
            # Save venv path for later stages
            venv_path_file = output_dir / "venv_path.txt"
            with open(venv_path_file, 'w') as f:
                f.write(str(unified_venv))
            logger.info(f"Saved virtual environment path to {venv_path_file}")
            
            if args.config_venv:
                logger.info("Virtual environment configuration completed. Exiting as requested.")
                return 0
        else:
            # Load venv path from file if not configuring
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
    
    except Exception as e:
        logger.error(f"Error in global pipeline execution: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 1


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
    """Get a set of all repository identifiers that have already been processed.
    
    The "repository" field in results.jsonl contains:
     - For GitHub repos: "username/repo@sha"
     - For local directories: The absolute path to the directory
    
    Args:
        results_jsonl_path: Path to the results.jsonl file
    
    Returns:
        Set[str]: Set of repository identifiers that have been processed
    """
    processed_repos = set()
    
    if not results_jsonl_path.exists():
        return processed_repos
    
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
    
    # Pre-determine repo identifier for checking if it's already processed
    repo_identifier = None
    if repo_info:
        full_name, sha = repo_info
        repo_identifier = f"{full_name}@{sha}"
    elif local_path:
        local_path_resolved = Path(local_path)
        repo_identifier = str(local_path_resolved)
    
    # We no longer need to check if the repository is already processed here
    # because it's already filtered out in the main process when using --skip-processed
    # Only check in single repo mode (when called directly, not via the worker pool)
    # Check by the presence of args.repo_list or args.local_list attributes if this is called from a pool
    # if (repo_identifier and args.skip_processed and not args.overwrite and 
    #         not hasattr(args, '_is_from_pool') and has_repo_been_processed(results_jsonl_path, repo_identifier)):
    #     logger.info(f"Skipping already processed repository: {repo_identifier}")
    #     return 0
    
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
        "logs": []
    }
    
    def add_log_entry(message: str, level: str = "INFO", **kwargs):
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
        # Initialize repository directly in output directory
        repo_manager = RepoManager(output_dir=output_dir, logger=logger)
        
        # Now that we have repo_manager, determine the repository identifier
        if repo_info:
            full_name, sha = repo_info
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

            # Store test results in the result data
            result_data["tests"]["found"] = total_test_cases
            result_data["tests"]["passed"] = success_count
            result_data["tests"]["failed"] = failure_count
            result_data["tests"]["skipped"] = skip_count
            result_data["tests"]["details"] = test_results["test_results"]
            
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
        
        add_log_entry(f"Process completed in {elapsed_time:.2f} seconds")
        add_log_entry(f"Project configured in {working_dir}")
        
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
    
    # If skip_processed is enabled, filter out already processed repositories
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results_jsonl_path = output_dir / "results.jsonl"
    
    if args.skip_processed and not args.overwrite and results_jsonl_path.exists():
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
        logger.info(f"Processing {len(unprocessed_repos)} out of {len(repo_infos)} repositories (skipping {skipped_count} already processed)")
        repo_infos = unprocessed_repos
    
    if not repo_infos:
        logger.info("All repositories have already been processed")
        return 0
    
    # Create argument tuples for the wrapper function
    arg_tuples = [(args, repo_info) for repo_info in repo_infos]
    
    # Create a pool of worker processes
    with multiprocessing.Pool(processes=args.num_workers) as pool:
        # Process repositories in parallel with progress bar
        pbar = tqdm(total=len(repo_infos), desc="Processing repositories", unit="repo")
        results = []
        
        # Use imap_unordered for better real-time progress updates
        for result in pool.imap_unordered(_process_repo_wrapper, arg_tuples):
            results.append(result)
            pbar.update(1)
        
        pbar.close()
    
    # Check if any process failed
    return 1 if any(result != 0 for result in results) else 0


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
    
    if args.skip_processed and not args.overwrite and results_jsonl_path.exists():
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
        
        logger.info(f"Processing {len(filtered_dir_paths)} out of {len(dir_paths)} directories (skipping {len(dir_paths) - len(filtered_dir_paths)} already processed)")
        dir_paths = filtered_dir_paths
    
    if not dir_paths:
        logger.info("All directories have already been processed")
        return 0
    
    # Create argument tuples for the wrapper function
    arg_tuples = [(args, dir_path) for dir_path in dir_paths]
    
    # Create a pool of worker processes
    with multiprocessing.Pool(processes=args.num_workers) as pool:
        # Process directories in parallel with progress bar
        pbar = tqdm(total=len(dir_paths), desc="Processing directories", unit="dir")
        results = []
        
        # Use imap_unordered for better real-time progress updates
        for result in pool.imap_unordered(_process_local_wrapper, arg_tuples):
            results.append(result)
            pbar.update(1)
        
        pbar.close()
    
    # Check if any process failed
    return 1 if any(result != 0 for result in results) else 0


def main():
    """Main entry point for the application."""
    try:
        # Parse arguments
        args = parse_arguments()
        
        # Configure logging for the main process
        logger = configure_process_logging(args.verbose)
        
        # If using global mode, use the unified pipeline
        if getattr(args, 'global_mode', False):
            if not (args.repo_list or args.local_list):
                logger.error("Global mode requires --repo-list or --local-list")
                return 1
            return run_unified_pipeline(args)
        
        # Process based on the mode for regular operation
        if args.repo_list:
            return process_repo_list(args)
        elif args.local_list:
            return process_local_list(args)
        else:
            # Single repository/directory mode
            return process_single_repo(args, args.repo if args.repo else None, args.local if args.local else None)
    except Exception as e:
        # Log any errors during main execution
        logger = logging.getLogger(__name__)
        logger.error(f"Error in main execution: {e}")
        
        # Attempt to clean up temporary directories even if main fails
        cleanup_temp_directories(logger)
        
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