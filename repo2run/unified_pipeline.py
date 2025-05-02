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

Note:
    The pipeline can also be accessed through the main CLI with the --global flag.
    When using the main CLI, the pipeline can be run in separate stages:
    
    # Stage 1: Extract dependencies
    repo2run --global --repo-list repos.txt --output-dir output_path --extract-dep
    
    # Stage 2: Configure virtual environment
    repo2run --global --repo-list repos.txt --output-dir output_path --config-venv
    
    # Stage 3: Run tests
    repo2run --global --repo-list repos.txt --output-dir output_path --run-test

Options:
    --repo-list FILE       Text file containing list of repositories (format: user/repo sha)
    --local-list FILE      Text file containing list of local directories
    --output-dir DIR       Directory to store output files (default: output)
    --workspace-dir DIR    Directory to use as workspace (default: temporary directory)
    --timeout SECONDS      Timeout in seconds (default: 1800 - 0.5 houra)
    --verbose              Enable verbose logging
    --overwrite            Overwrite existing output directory if it exists
    --use-uv               Use UV for dependency management (default: False, use pip/venv)
    --skip-processed       Skip repositories that have already been processed (based on repo_req.jsonl)
    --repo-range START END Process only a range of repositories (e.g., 0 100 for repos 0-99). Zero-indexed.
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
import traceback
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
        default=1800,
        help='Timeout in seconds (default: 1800 - 0.5 houra)'
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
        default=os.cpu_count(),
        help='Maximum number of worker threads for parallel processing (default: 4)'
    )
    parser.add_argument(
        '--skip-processed',
        action='store_true',
        help='Skip repositories that have already been processed (based on repo_req.jsonl)'
    )
    parser.add_argument(
        '--repo-range',
        type=int,
        nargs=2,
        metavar=('START', 'END'),
        help='Process only a range of repositories (e.g., 0 100 for repos 0-99). Zero-indexed.'
    )
    
    # Add extract-tests flag
    parser.add_argument(
        '--extract-tests',
        action='store_true',
        help='Extract test files from repositories and write them to test.jsonl (repositories will not be copied to output folder and results.jsonl will not be generated)'
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


def load_processed_repositories(output_dir):
    """
    Load processed repositories from the repo_req.jsonl file.
    
    Args:
        output_dir: Output directory
        
    Returns:
        set: Set of repository identifiers that have already been processed
    """
    processed_repos = set()
    repo_req_path = output_dir / "repo_req.jsonl"
    logger = logging.getLogger(__name__)
    
    if not repo_req_path.exists():
        logger.info(f"No existing repo_req.jsonl found at {repo_req_path}")
        return processed_repos
    
    try:
        with open(repo_req_path, 'r') as f:
            line_count = 0
            valid_records = 0
            for line_number, line in enumerate(f, 1):
                line = line.strip()
                if not line:  # Skip empty lines
                    continue
                    
                try:
                    record = json.loads(line)
                    line_count += 1
                    if "repository" in record:
                        repo_id = record["repository"]
                        processed_repos.add(repo_id)
                        valid_records += 1
                    else:
                        logger.warning(f"Line {line_number}: Missing 'repository' field in JSON record")
                except json.JSONDecodeError as e:
                    logger.warning(f"Line {line_number}: Invalid JSON: {str(e)}")
                except Exception as e:
                    logger.warning(f"Line {line_number}: Unexpected error: {str(e)}")
        
        if line_count > 0:
            logger.info(f"Processed {line_count} lines from repo_req.jsonl: {valid_records} valid records")
            logger.info(f"Found {len(processed_repos)} unique repository identifiers")
        else:
            logger.info(f"repo_req.jsonl exists but is empty or contains no valid records")
    except Exception as e:
        logger.warning(f"Error reading repo_req.jsonl: {str(e)}")
    
    return processed_repos


def extract_dependencies(repo_info, output_dir, args, repo_req_data, all_dependencies):
    """
    Extract dependencies from a single repository and write to JSONL.
    
    Args:
        repo_info: Repository information (tuple or Path)
        output_dir: Output directory
        args: Command line arguments
        repo_req_data: Dictionary to store repository requirements
        all_dependencies: Set to store all unique dependencies
    
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
            # Use absolute path without resolving symlinks for better performance
            repo_id = str(local_path.absolute())
        
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
                # Skip adding to all_dependencies in extract_dep mode
                if not getattr(args, 'extract_dep', False):
                    all_dependencies.add(package_name)  # Add to the global set
        
        # Store in repo_req_data (if it's a Manager dict)
        if hasattr(repo_req_data, '__setitem__'):
            repo_req_data[repo_id] = list(packages)
        
        # Write to JSONL file
        repo_req_path = output_dir / "repo_req.jsonl"
        with open(repo_req_path, 'a') as f:
            json.dump({"repository": repo_id, "dependencies": list(packages)}, f)
            f.write('\n')
        
        return repo_id, packages
    
    except Exception as e:
        logger.error(f"Failed to extract dependencies from {repo_info}: {str(e)}")
        return None, set()


def build_dependencies_from_jsonl(output_dir):
    """
    Build the complete set of unique dependencies from repo_req.jsonl file.
    
    Args:
        output_dir: Output directory containing repo_req.jsonl
        
    Returns:
        set: Set of all unique dependencies across all repositories
    """
    logger = logging.getLogger(__name__)
    all_deps = set()
    jsonl_path = output_dir / "repo_req.jsonl"
    
    if not jsonl_path.exists():
        logger.error(f"Repository requirements file not found at {jsonl_path}")
        return all_deps
    
    try:
        with open(jsonl_path, 'r') as f:
            line_count = 0
            for line in f:
                try:
                    record = json.loads(line.strip())
                    if "dependencies" in record:
                        dependencies = record["dependencies"]
                        all_deps.update(dependencies)
                        line_count += 1
                except json.JSONDecodeError:
                    logger.warning(f"Skipping malformed line in {jsonl_path}")
                    continue
        
        logger.info(f"Built dependency set from {line_count} repositories in {jsonl_path}")
        logger.info(f"Found {len(all_deps)} unique dependencies across all repositories")
    except Exception as e:
        logger.error(f"Error reading {jsonl_path}: {e}")
    
    return all_deps


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
    
    # Load processed repositories if skip-processed is enabled
    processed_repos = set()
    if args.skip_processed:
        processed_repos = load_processed_repositories(output_dir)
        logger.info(f"Found {len(processed_repos)} previously processed repositories")
        
        # Filter repositories to keep only those not already processed
        repositories_to_process = []
        for repo in repositories:
            if isinstance(repo, tuple):
                repo_id = f"{repo[0]}@{repo[1]}"
            else:
                # Use absolute path without resolving symlinks for better performance
                repo_id = str(repo)
                
            if repo_id not in processed_repos:
                repositories_to_process.append(repo)
            else:
                logger.info(f"Skipping already processed repository: {repo_id}")
                
        logger.info(f"Processing {len(repositories_to_process)} new repositories")
        repositories = repositories_to_process
        
        # If no new repositories to process, return early
        if not repositories:
            logger.info("No new repositories to process. Skipping dependency analysis.")
            # In extract-dep mode, still return an empty set as we'll rebuild it later
            if getattr(args, 'extract_dep', False):
                return set(), {}
                
            # For other modes, read from existing dependencies
            all_dependencies = set()
            requirements_path = output_dir / "requirements.txt"
            if requirements_path.exists():
                with open(requirements_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            all_dependencies.add(line)
            
            # Return empty repo_req_data as we're not processing anything new
            return all_dependencies, {}
    
    # Dictionary to store requirements by repository (use a thread-safe manager)
    from multiprocessing import Manager
    manager = Manager()
    repo_req_data = manager.dict()
    
    # Set to store all unique dependencies
    # Skip accumulating in all_dependencies in extract-dep mode to reduce overhead
    all_dependencies = set()
    
    # If using skip-processed and not in extract-dep mode, read existing requirements
    if args.skip_processed and not getattr(args, 'extract_dep', False):
        requirements_path = output_dir / "requirements.txt"
        if requirements_path.exists():
            with open(requirements_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        all_dependencies.add(line)
            logger.info(f"Loaded {len(all_dependencies)} existing dependencies from requirements.txt")
    
    # Print summary of repositories being processed
    if len(repositories) > 0:
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
    
    # Clear repo_req.jsonl if not using skip-processed to avoid duplicate entries
    if not args.skip_processed:
        repo_req_jsonl_path = output_dir / "repo_req.jsonl"
        if repo_req_jsonl_path.exists():
            with open(repo_req_jsonl_path, 'w') as f:
                # Empty the file
                pass
    
    # If no repositories to process, return early with existing dependencies
    if not repositories:
        return all_dependencies, {}
    
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
        # Initialize the progress bar outside the dictionary comprehension
        with tqdm(total=len(repositories), desc="Extracting dependencies", 
                 bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]") as pbar:
            
            future_to_repo = {
                executor.submit(extract_dependencies, repo, output_dir, args, repo_req_data, all_dependencies): repo
                for repo in repositories
            }
            
            for future in concurrent.futures.as_completed(future_to_repo):
                repo = future_to_repo[future]
                try:
                    repo_id, packages = future.result()
                    if repo_id:
                        # Display what we found for this repository
                        repo_name = repo_id.split('@')[0] if '@' in repo_id else repo_id
                        pbar.set_postfix_str(f"Found {len(packages)} packages in {repo_name}")
                    
                        # In extract-dep mode, we don't need to keep updating all_dependencies
                        # as we'll rebuild it in config-venv stage
                        if not getattr(args, 'extract_dep', False):
                            all_dependencies.update(packages)
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
    
    # If we're in extract-dep mode, we don't need to compute the full dependencies set
    # since that will be done in config-venv stage
    if getattr(args, 'extract_dep', False):
        logger.info("Skipping unified dependencies computation in extract-dep mode")
        return set(), repo_req_data_dict
    
    # For non-extract-dep modes:
    # Ensure we have all dependencies by building from JSONL if needed
    if len(all_dependencies) == 0:
        logger.info("Building complete dependency set from JSONL file")
        all_dependencies = build_dependencies_from_jsonl(output_dir)
    
    # Save all dependencies to requirements.txt
    requirements_path = output_dir / "requirements.txt"
    logger.info(f"Saving unified requirements to {requirements_path}")
    with open(requirements_path, 'w') as f:
        for dep in sorted(all_dependencies):
            f.write(f"{dep}\n")
    
    # Save repo requirements to file (only if not using skip-processed or if we have new data)
    if not args.skip_processed or repo_req_data_dict:
        repo_req_path = output_dir / "repo_req.json"
        logger.info(f"Saving repository requirements to {repo_req_path}")
        
        # If using skip-processed and repo_req.json exists, merge with new data
        if args.skip_processed and repo_req_path.exists():
            try:
                with open(repo_req_path, 'r') as f:
                    existing_data = json.load(f)
                # Merge existing data with new data
                existing_data.update(repo_req_data_dict)
                repo_req_data_dict = existing_data
            except Exception as e:
                logger.warning(f"Error reading existing repo_req.json: {e}")
        
        with open(repo_req_path, 'w') as f:
            json.dump(repo_req_data_dict, f, indent=2)
    
    # Print summary of findings
    logger.info(f"✨ Dependency analysis complete!")
    logger.info(f"📊 Summary:")
    logger.info(f"  - Found {len(all_dependencies)} unique dependencies across all repositories")
    
    # Find most common dependencies (top 5)
    dep_counts = {}
    for deps in repo_req_data_dict.values():
        for dep in deps:
            dep_counts[dep] = dep_counts.get(dep, 0) + 1
    
    top_deps = sorted(dep_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    logger.info(f"  - Top dependencies:")
    for dep, count in top_deps:
        logger.info(f"    • {dep}: used in {count} repositories ({count/len(repositories) if repositories else 1:.1%})")
    
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


def run_tests_for_repo(repo_info, output_dir, unified_venv, args, test_file_list=None, test_file_metadata=None):
    """
    Run tests for a single repository using the unified virtual environment.
    
    Args:
        repo_info: Repository information (tuple or Path)
        output_dir: Output directory
        unified_venv: Path to the unified virtual environment (can be None to use current environment)
        args: Command line arguments
        test_file_list: Optional list of test file paths
        test_file_metadata: Optional dictionary to store additional metadata for test files
    
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
        }
    }
    
    def add_log_entry(message, level="INFO", **kwargs):
        """Add a log entry to the logger only."""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if level == "INFO":
            logger.info(message)
        elif level == "WARNING":
            logger.warning(message)
        elif level == "ERROR":
            logger.error(message)
    
    try:
        # Set up repository information
        working_dir = None
        
        if isinstance(repo_info, tuple):
            # GitHub repository
            full_name, sha = repo_info
            repo_name = full_name
            result_data["repository"] = f"{full_name}@{sha}"
            
            # Check if the repository has already been cloned
            if hasattr(args, 'workspace_dir') and args.workspace_dir:
                workspace_dir = Path(args.workspace_dir)
                repo_dir = workspace_dir / full_name.replace("/", "_") / sha
                if repo_dir.exists():
                    add_log_entry(f"Using existing repository at {repo_dir}")
                    working_dir = repo_dir
                else:
                    # Clone the repository to the workspace directory
                    add_log_entry(f"Cloning repository {full_name}@{sha} to {repo_dir}")
                    try:
                        repo_manager.clone_repository(full_name, sha, repo_dir)
                        working_dir = repo_dir
                    except Exception as e:
                        add_log_entry(f"Failed to clone repository: {str(e)}", level="ERROR")
                        result_data["status"] = "error"
                        result_data["error"] = f"Failed to clone repository: {str(e)}"
                        result_data["execution"]["elapsed_time"] = time.time() - result_data["execution"]["start_time"]
                        return result_data
            else:
                # Clone to a temporary directory
                temp_dir = tempfile.mkdtemp(prefix="repo2run_")
                add_log_entry(f"Cloning repository {full_name}@{sha} to temporary directory {temp_dir}")
                try:
                    repo_manager.clone_repository(full_name, sha, temp_dir)
                    working_dir = Path(temp_dir)
                except Exception as e:
                    add_log_entry(f"Failed to clone repository: {str(e)}", level="ERROR")
                    result_data["status"] = "error"
                    result_data["error"] = f"Failed to clone repository: {str(e)}"
                    result_data["execution"]["elapsed_time"] = time.time() - result_data["execution"]["start_time"]
                    # Clean up temporary directory
                    try:
                        shutil.rmtree(temp_dir)
                    except Exception:
                        pass
                    return result_data
        else:
            # Local directory
            repo_path = Path(repo_info)
            repo_name = repo_path.name
            result_data["repository"] = str(repo_path)
            
            # Use the local repository directly
            working_dir = repo_path
        
        add_log_entry(f"Working directory set to {working_dir}")
        
        # Process test files if provided
        test_files = None
        test_metadata = {}  # Will store metadata for each test file
        
        if test_file_list:
            # Convert test file paths to Path objects relative to working_dir
            test_files = []
            skipped_files = []
            
            # Check if we should require tested_files
            require_tested_files = hasattr(args, 'require_tested_files') and args.require_tested_files
            
            for test_file_path in test_file_list:
                try:
                    # Check if this test file has tested_files metadata
                    if require_tested_files and test_file_metadata and test_file_path in test_file_metadata:
                        metadata = test_file_metadata[test_file_path]
                        tested_files = metadata.get("tested_files", [])
                        
                        # Skip test files without tested_files information
                        if not tested_files:
                            add_log_entry(f"Skipping test file {test_file_path} because it doesn't have tested_files information", level="WARNING")
                            skipped_files.append(test_file_path)
                            continue
                    
                    # Try multiple ways to locate the test file
                    # 1. Direct path from working directory
                    file_path = working_dir / test_file_path
                    
                    # 2. If not found, try with just the filename
                    if not file_path.exists():
                        file_path = working_dir / Path(test_file_path).name
                    
                    # 3. Try a glob pattern based on the filename
                    if not file_path.exists():
                        file_name = Path(test_file_path).name
                        glob_pattern = f"**/{file_name}"
                        glob_results = list(working_dir.glob(glob_pattern))
                        if glob_results:
                            file_path = glob_results[0]  # Use the first match
                    
                    # Add the file if it exists
                    if file_path.exists():
                        test_files.append(file_path)
                        relative_path = file_path.relative_to(working_dir)
                        add_log_entry(f"Found test file: {relative_path}")
                        
                        # Capture metadata for this test file if available
                        if test_file_metadata and test_file_path in test_file_metadata:
                            # Store with both absolute and relative paths for easier lookup
                            test_metadata[str(file_path)] = test_file_metadata[test_file_path]
                            test_metadata[str(relative_path)] = test_file_metadata[test_file_path]
                            
                            # Log tested files
                            tested_files = test_file_metadata[test_file_path].get("tested_files", [])
                            
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
                                    add_log_entry(f"Removed {len(tested_files) - len(unique_tested_files)} duplicate entries from tested_files for {relative_path}")
                                
                                # Update the metadata with deduplicated tested_files
                                test_file_metadata[test_file_path]["tested_files"] = unique_tested_files
                                test_metadata[str(file_path)]["tested_files"] = unique_tested_files
                                test_metadata[str(relative_path)]["tested_files"] = unique_tested_files
                                tested_files = unique_tested_files
                            
                            if tested_files:
                                add_log_entry(f"Test file {relative_path} has {len(tested_files)} tested files")
                    else:
                        add_log_entry(f"Test file not found: {test_file_path}", level="WARNING")
                except Exception as e:
                    add_log_entry(f"Error processing test file path {test_file_path}: {str(e)}", level="WARNING")
            
            if test_files:
                add_log_entry(f"Using {len(test_files)} test files from test.jsonl")
            else:
                add_log_entry("None of the provided test files were found, will use auto-discovery instead", level="WARNING")
                test_files = None
            
            # Add information about skipped files to result_data
            if skipped_files:
                add_log_entry(f"Skipped {len(skipped_files)} test files due to missing tested_files information", level="WARNING")
                result_data["skipped_files"] = {
                    "count": len(skipped_files),
                    "files": skipped_files,
                    "reason": "missing_tested_files"
                }
        
        # Run tests
        test_runner = TestRunner(working_dir, venv_path=unified_venv, use_uv=args.use_uv, 
                               logger=logger, timeout=args.timeout, test_files=test_files, 
                               test_metadata=test_metadata)
        
        if not test_files:
            add_log_entry("Looking for tests in the repository")
            test_files = test_runner.get_test_files()
        
        if not test_files:
            add_log_entry("No tests found. Marking repository as 'skip'")
            result_data["status"] = "skip"
            return result_data
        
        add_log_entry(f"Found {len(test_files)} test files")
        
        # When specific test files were provided, ensure that ONLY those files are used
        if test_file_list is not None:
            add_log_entry("Enforcing strict test file selection - will only use input test files")
            # Convert test files to strings for comparison
            test_file_paths = [str(file_path) for file_path in test_files]
            
            # Extract file names (without paths) for flexible matching
            test_file_names = [Path(file_path).name for file_path in test_file_paths]
            input_file_names = [Path(file_path).name for file_path in test_file_list]
            
            # Log what's being included
            add_log_entry(f"Input test file names: {input_file_names}")
            add_log_entry(f"Found test file names: {test_file_names}")
            
            # Filter test files to include only those that match the input files
            filtered_test_files = []
            for test_file in test_files:
                test_file_str = str(test_file)
                test_file_name = Path(test_file_str).name
                
                # Include file if its full path matches an input file OR if just the filename matches
                if any(input_file in test_file_str for input_file in test_file_list) or test_file_name in input_file_names:
                    filtered_test_files.append(test_file)
                    add_log_entry(f"Including test file: {test_file_str}")
                else:
                    add_log_entry(f"Excluding test file: {test_file_str} (not in input list)")
            
            # Replace test_files with the filtered list
            test_files = filtered_test_files
            add_log_entry(f"Using {len(test_files)} test files after filtering")
            
            # Update the test runner with the filtered list
            test_runner.test_files = test_files
        
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
        
        # If we have individual tests, use those for more accurate counts
        if "individual_tests" in test_results and test_results["individual_tests"]:
            individual_tests = test_results["individual_tests"]
            success_count = sum(1 for t in individual_tests if t.get("status") == "passed")
            failure_count = sum(1 for t in individual_tests if t.get("status") in ["failed", "failure", "error"])
            skip_count = sum(1 for t in individual_tests if t.get("status") == "skipped")
            total_test_cases = len(individual_tests)
            has_failures = failure_count > 0
            add_log_entry(f"Using counts from {total_test_cases} individual tests: {success_count} passed, {failure_count} failed, {skip_count} skipped")
        
        # Update result data with test results
        result_data["tests"]["found"] = test_results.get("tests_found", 0)
        result_data["tests"]["passed"] = test_results.get("tests_passed", 0)
        result_data["tests"]["failed"] = test_results.get("tests_failed", 0)
        result_data["tests"]["skipped"] = test_results.get("tests_skipped", 0)
        result_data["tests"]["details"] = test_results.get("test_results", [])
        
        # Add individual test results if available
        if "individual_tests" in test_results:
            result_data["individual_tests"] = test_results["individual_tests"]
            add_log_entry(f"Collected {len(test_results['individual_tests'])} individual test results")
            
            # Organize individual tests by file path and add test name lists to test files
            tests_by_file = {}
            
            # Group tests by file
            for test in test_results["individual_tests"]:
                file_path = test.get("file_path", "")
                test_name = test.get("name", "")
                status = test.get("status", "")
                classname = test.get("classname", "")
                message = test.get("message", "")
                
                if not file_path:
                    continue
                
                # Initialize the file entry if needed
                if file_path not in tests_by_file:
                    tests_by_file[file_path] = []
                
                # Add test object to the list
                tests_by_file[file_path].append({
                    "name": test_name,
                    "classname": classname,
                    "status": status,
                    "message": message
                })
            
            # Update test file data in the FINAL result_data structure
            if "test_files" in test_results:
                # Initialize test_files in result_data if not present
                if "test_files" not in result_data:
                    result_data["test_files"] = [
                        {"path": test_file["path"], "status": test_file["status"], "tests": []} 
                        for test_file in test_results["test_files"]
                    ]
                
                # Make sure we have test_files in result_data
                for i, test_file in enumerate(test_results["test_files"]):
                    file_path = test_file.get("path", "")
                    
                    # Make sure all test files from test_results are in result_data
                    if i >= len(result_data.get("test_files", [])):
                        result_data.setdefault("test_files", []).append({
                            "path": file_path,
                            "status": test_file.get("status", "unknown"),
                            "tests": []
                        })
                    
                    # Add tests to result_data test files
                    if file_path in tests_by_file:
                        # Add tests array directly to the result_data structure
                        result_data["test_files"][i]["tests"] = tests_by_file[file_path]
                        
                        # Add summary field with test counts 
                        if "summary" not in result_data["test_files"][i]:
                            result_data["test_files"][i]["summary"] = {}
                        
                        # Ensure the summary counts match the actual tests
                        tests = result_data["test_files"][i]["tests"]
                        result_data["test_files"][i]["summary"] = {
                            "passed_tests": sum(1 for t in tests if t.get("status") == "passed"),
                            "failed_tests": sum(1 for t in tests if t.get("status") in ["failure", "error"]),
                            "skipped_tests": sum(1 for t in tests if t.get("status") == "skipped")
                        }
                        
                        add_log_entry(f"Added {len(tests)} tests to result_data for file {file_path}")
            
            # Make sure all test files have the required fields even if they don't have individual tests
            if "test_files" in result_data:
                for test_file in result_data["test_files"]:
                    # Make sure the test_file has the required field
                    if "tests" not in test_file:
                        test_file["tests"] = []
                    
                    # Make sure summary is present and correct
                    if "summary" not in test_file:
                        test_file["summary"] = {
                            "passed_tests": sum(1 for t in test_file.get("tests", []) if t.get("status") == "passed"),
                            "failed_tests": sum(1 for t in test_file.get("tests", []) if t.get("status") in ["failure", "error"]),
                            "skipped_tests": sum(1 for t in test_file.get("tests", []) if t.get("status") == "skipped")
                        }
        
        # Set status based on test results
        result_data["status"] = test_results.get("status", "unknown")
        
        # Set execution time
        result_data["execution"]["elapsed_time"] = time.time() - result_data["execution"]["start_time"]
        
        add_log_entry(f"Completed tests with status: {result_data['status']}")
        
        return result_data
    except Exception as e:
        # Handle unhandled exceptions
        add_log_entry(f"Unhandled exception during test execution: {str(e)}", level="ERROR")
        result_data["status"] = "error"
        result_data["error"] = f"Unhandled exception: {str(e)}"
        result_data["execution"]["elapsed_time"] = time.time() - result_data["execution"]["start_time"]
        
        # Add traceback
        traceback_str = traceback.format_exc()
        add_log_entry(f"Traceback: {traceback_str}", level="ERROR")
        
        return result_data
    finally:
        # Check if we need to clean up a temporary directory
        if isinstance(repo_info, tuple) and not hasattr(args, 'workspace_dir'):
            if 'temp_dir' in locals() and temp_dir and Path(temp_dir).exists():
                add_log_entry(f"Cleaning up temporary directory {temp_dir}")
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    add_log_entry(f"Failed to clean up temporary directory: {str(e)}", level="WARNING")


def process_repository(repo, output_dir, unified_venv, args, repo_test_info=None):
    """Process a single repository and handle errors.
    
    Args:
        repo: Repository information (tuple or Path)
        output_dir: Output directory path
        unified_venv: Virtual environment path
        args: Command line arguments
        repo_test_info: Optional dictionary mapping repository paths to test file information
    
    Returns:
        dict: Test results for the repository
    """
    try:
        test_file_list = None
        test_file_metadata = None
        
        if repo_test_info:
            repo_key = str(repo)
            if repo_key in repo_test_info:
                test_files_info = repo_test_info[repo_key]
                if test_files_info:
                    test_file_list = []
                    test_file_metadata = {}
                    for test_info in test_files_info:
                        if "path" in test_info:
                            test_path = test_info["path"]
                            test_file_list.append(test_path)
                            test_file_metadata[test_path] = {
                                "tested_files": test_info.get("tested_files", [])
                            }
        
        result = run_tests_for_repo(repo, output_dir, unified_venv, args, 
                                  test_file_list=test_file_list,
                                  test_file_metadata=test_file_metadata)
        return result
    except Exception as e:
        # Create an error result
        repo_str = f"{repo[0]}@{repo[1]}" if isinstance(repo, tuple) else str(repo)
        return {
            "repository": repo_str,
            "status": "error",
            "error": str(e),
            "tests": {"found": 0, "passed": 0, "failed": 0, "skipped": 0, "details": []},
            "execution": {
                "start_time": time.time(),
                "elapsed_time": 0
            }
        }


def run_tests_parallel(repositories, output_dir, unified_venv, args, repo_test_info=None):
    """
    Run tests for all repositories in parallel.
    
    Args:
        repositories: List of repositories
        output_dir: Output directory
        unified_venv: Path to the unified virtual environment (can be None to use current environment)
        args: Command line arguments
        repo_test_info: Optional dictionary mapping repository paths to test file information
    
    Returns:
        dict: Test results by repository
    """
    logger = logging.getLogger(__name__)
    logger.info(f"🧪 Running tests for {len(repositories)} repositories")
    
    # Print environment info
    logger.info(f"📂 Environment details:")
    if unified_venv:
        logger.info(f"  - Using virtual environment at: {unified_venv}")
        
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
            logger.info(f"  - Python version in venv: {result.stdout.strip()}")
        except Exception:
            logger.info(f"  - Python version in venv: Unknown")
    else:
        logger.info(f"  - Using current Python environment: {sys.executable}")
        logger.info(f"  - Python version: {sys.version.split()[0]}")
    
    # Increase default max_workers for better parallelism
    max_workers = args.max_workers
    # Use more workers for larger numbers of repositories
    # but don't exceed available CPU cores
    import multiprocessing
    import signal
    import psutil
    import threading
    import queue
    import functools
    available_cores = multiprocessing.cpu_count()
    suggested_workers = min(available_cores, len(repositories), 16)  
    max_workers = suggested_workers
    logger.info(f"Using {max_workers} worker processes for parallel test execution")
    
    def kill_process_tree(pid):
        """Kill a process and all its children."""
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            
            # Send SIGTERM to children first
            for child in children:
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            
            # Send SIGTERM to parent
            try:
                parent.terminate()
            except psutil.NoSuchProcess:
                pass
            
            # Wait for processes to terminate
            gone, alive = psutil.wait_procs(children + [parent], timeout=3)
            
            # If any processes are still alive, send SIGKILL
            for p in alive:
                try:
                    p.kill()
                except psutil.NoSuchProcess:
                    pass
                
            # Double check if parent is still alive
            try:
                if parent.is_running():
                    parent.kill()  # Force kill if still running
            except psutil.NoSuchProcess:
                pass
            
            # Double check children
            for child in children:
                try:
                    if child.is_running():
                        child.kill()  # Force kill if still running
                except psutil.NoSuchProcess:
                    pass
        except psutil.NoSuchProcess:
            pass
        except Exception as e:
            logger.warning(f"Error killing process tree {pid}: {e}")
    
    def cleanup_process(future, repo_name=None):
        """Clean up a process associated with a future."""
        if not future.done():
            try:
                # Get the process ID if available
                if hasattr(future, '_process'):
                    pid = future._process.pid
                    if repo_name:
                        logger.warning(f"Killing process tree for repository {repo_name} (PID: {pid})")
                    kill_process_tree(pid)
                
                # Cancel the future
                future.cancel()
                
                # Wait a short time for cancellation to take effect
                time.sleep(0.1)
                
                # Force cancel again if still not done
                if not future.done():
                    future.cancel()
            except Exception as e:
                logger.warning(f"Error cleaning up process: {e}")
    
    # Create a threading Event for signaling shutdown
    shutdown_event = threading.Event()
    
    def worker_init():
        """Initialize worker process"""
        # Ignore SIGINT in worker processes
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        
        # Set up process group for easier cleanup
        os.setpgrp()
    
    # Process repositories in parallel
    all_results = []
    executor = None
    timeout_threads = []  # Keep track of timeout threads
    
    try:
        # Create a partial function with fixed arguments
        process_repo = functools.partial(
            process_repository,
            output_dir=output_dir,
            unified_venv=unified_venv,
            args=args,
            repo_test_info=repo_test_info
        )
        
        # Use a process pool for test running to enable proper timeout handling
        executor = concurrent.futures.ProcessPoolExecutor(
            max_workers=max_workers, 
            initializer=worker_init
        )
        
        # Submit all tasks
        future_to_repo = {}
        for repo in repositories:
            if shutdown_event.is_set():
                break
            future = executor.submit(process_repo, repo)
            future_to_repo[future] = repo
        
        # Process results as they complete with a detailed progress bar
        total_tests = 0
        passed_tests = 0
        failed_tests = 0
        skipped_tests = 0
        total_individual_tests = 0
        passed_individual_tests = 0
        failed_individual_tests = 0
        skipped_individual_tests = 0
        total_skipped_files = 0
        
        # Create a progress bar with more information
        with tqdm(total=len(repositories), desc="Running tests", 
                 bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]") as pbar:
            
            completed_futures = set()
            while len(completed_futures) < len(future_to_repo):
                if shutdown_event.is_set():
                    break
                
                # Check for completed futures
                newly_completed = {f for f in future_to_repo if f.done() and f not in completed_futures}
                
                for future in newly_completed:
                    repo = future_to_repo[future]
                    completed_futures.add(future)
                    
                    try:
                        # Display which repository is currently being processed
                        repo_name = repo[0] if isinstance(repo, tuple) else Path(repo).name
                        pbar.set_postfix_str(f"Processing {repo_name}")
                        
                        try:
                            result = future.result(timeout=1)  # Short timeout for result retrieval
                        except concurrent.futures.TimeoutError:
                            # Clean up the process
                            cleanup_process(future, repo_name)
                            
                            # Create a timeout result
                            result = {
                                "repository": repo[0] + "@" + repo[1] if isinstance(repo, tuple) else str(repo),
                                "status": "error",
                                "error": f"Test execution timed out after {args.timeout} seconds",
                                "tests": {"found": 0, "passed": 0, "failed": 0, "skipped": 0, "details": []},
                                "execution": {
                                    "start_time": time.time() - args.timeout,
                                    "elapsed_time": args.timeout
                                }
                            }
                            logger.error(f"Repository {repo_name} timed out after {args.timeout} seconds")
                        
                        if result is not None:
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
                            
                            # Count individual tests if available
                            if "individual_tests" in result:
                                individual_tests = result["individual_tests"]
                                total_individual_tests += len(individual_tests)
                                passed_individual_tests += sum(1 for t in individual_tests if t.get("status") == "passed")
                                failed_individual_tests += sum(1 for t in individual_tests if t.get("status") in ["failed", "failure", "error"])
                                skipped_individual_tests += sum(1 for t in individual_tests if t.get("status") == "skipped")
                            
                            # Track skipped files
                            if "skipped_files" in result:
                                total_skipped_files += result["skipped_files"].get("count", 0)
                    
                    except Exception as e:
                        # Handle any other errors
                        repo_str = f"{repo[0]}@{repo[1]}" if isinstance(repo, tuple) else str(repo)
                        logger.error(f"Error processing {repo_str}: {str(e)}")
                        # Create an error result
                        error_result = {
                            "repository": repo_str,
                            "status": "error",
                            "error": str(e),
                            "tests": {"found": 0, "passed": 0, "failed": 0, "skipped": 0, "details": []},
                            "execution": {
                                "start_time": time.time(),
                                "elapsed_time": 0
                            }
                        }
                        all_results.append(error_result)
                        
                        # Clean up the process in case of error
                        cleanup_process(future, repo_str)
                    
                    pbar.update(1)
                
                # Check for hung processes
                current_time = time.time()
                for future, repo in future_to_repo.items():
                    if future not in completed_futures and not future.done():
                        # Get process info if available
                        if hasattr(future, '_process'):
                            try:
                                process = psutil.Process(future._process.pid)
                                if (current_time - process.create_time()) > args.timeout:
                                    repo_name = repo[0] if isinstance(repo, tuple) else Path(repo).name
                                    logger.warning(f"Process for {repo_name} exceeded timeout, killing...")
                                    cleanup_process(future, repo_name)
                                    completed_futures.add(future)
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass
                
                # Short sleep to prevent busy waiting
                time.sleep(0.1)
        
        # Cancel any remaining futures
        for future in future_to_repo:
            if not future.done():
                cleanup_process(future)
    
    except KeyboardInterrupt:
        logger.warning("Received keyboard interrupt, initiating graceful shutdown...")
        shutdown_event.set()
        
        # Cancel all pending futures
        for future in future_to_repo:
            if not future.done():
                cleanup_process(future)
        
        raise
    
    finally:
        # Set shutdown event to stop any monitoring threads
        shutdown_event.set()
        
        # Clean up all processes
        if executor is not None:
            try:
                # Cancel all pending futures
                for future in future_to_repo:
                    if not future.done():
                        cleanup_process(future)
                
                # Shutdown the executor with a timeout
                executor.shutdown(wait=False)
                
                # Give a short time for cleanup
                time.sleep(0.5)
                
                # Force kill any remaining processes
                for future in future_to_repo:
                    if hasattr(future, '_process'):
                        try:
                            kill_process_tree(future._process.pid)
                        except:
                            pass
                
                # Clean up executor resources safely
                try:
                    if hasattr(executor, '_processes'):
                        executor._processes.clear()
                except:
                    pass
                try:
                    if hasattr(executor, '_shutdown_thread'):
                        executor._shutdown_thread = None
                except:
                    pass
                try:
                    if hasattr(executor, '_call_queue'):
                        executor._call_queue.close()
                        executor._call_queue.join_thread()
                except:
                    pass
                try:
                    if hasattr(executor, '_result_queue'):
                        executor._result_queue.close()
                        executor._result_queue.join_thread()
                except:
                    pass
                
                # Stop any timeout threads
                for thread in timeout_threads:
                    try:
                        if thread.is_alive():
                            thread._stop()
                    except:
                        pass
            except:
                pass
            finally:
                try:
                    del executor
                except:
                    pass
        
        # Clean up any remaining processes
        try:
            current_process = psutil.Process()
            
            # First try graceful termination
            for child in current_process.children(recursive=True):
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            # Give processes time to terminate
            _, still_alive = psutil.wait_procs(current_process.children(), timeout=3)
            
            # Force kill any remaining processes
            for child in still_alive:
                try:
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                    
            # Double check for any new children
            for child in current_process.children(recursive=True):
                try:
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                    
            # Force cleanup of multiprocessing resources
            try:
                multiprocessing.current_process()._cleanup()
            except:
                pass
        except:
            pass
    
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
    
    # Print skipped files summary if any
    if total_skipped_files > 0:
        logger.info(f"  ⏭️  Skipped files: {total_skipped_files} test files skipped due to missing tested_files information")
    
    # Calculate percentages safely
    passed_percent = (passed_tests / total_tests * 100) if total_tests > 0 else 0
    failed_percent = (failed_tests / total_tests * 100) if total_tests > 0 else 0
    skipped_percent = (skipped_tests / total_tests * 100) if total_tests > 0 else 0
    
    logger.info(f"📊 Test case summary:")
    logger.info(f"  - Total test cases: {total_tests}")
    logger.info(f"  - Passed: {passed_tests} ({passed_percent:.1f}%)")
    logger.info(f"  - Failed: {failed_tests} ({failed_percent:.1f}%)")
    logger.info(f"  - Skipped: {skipped_tests} ({skipped_percent:.1f}%)")
    
    # Log individual test information if available
    if total_individual_tests > 0:
        passed_individual_percent = (passed_individual_tests / total_individual_tests * 100) if total_individual_tests > 0 else 0
        failed_individual_percent = (failed_individual_tests / total_individual_tests * 100) if total_individual_tests > 0 else 0
        skipped_individual_percent = (skipped_individual_tests / total_individual_tests * 100) if total_individual_tests > 0 else 0
        
        logger.info(f"📊 Individual test case summary:")
        logger.info(f"  - Total individual tests: {total_individual_tests}")
        logger.info(f"  - Passed: {passed_individual_tests} ({passed_individual_percent:.1f}%)")
        logger.info(f"  - Failed: {failed_individual_tests} ({failed_individual_percent:.1f}%)")
        logger.info(f"  - Skipped: {skipped_individual_tests} ({skipped_individual_percent:.1f}%)")
    
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
    """Main entry point for the unified pipeline."""
    start_time = time.time()
    
    args = parse_arguments()
    
    # Configure logging for the main process
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
        
        # Apply repository range filter if specified
        total_repos = len(repositories)
        if args.repo_range is not None:
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
        
        # Stage 2: Analyze dependencies across all repositories
        logger.info("\n" + "=" * 40)
        logger.info("🔍 STAGE 2: ANALYZING DEPENDENCIES")
        logger.info("=" * 40)
        all_dependencies, repo_req_data = analyze_dependencies_parallel(repositories, output_dir, args)
        
        # Stage 3: Create unified virtual environment with all dependencies
        logger.info("\n" + "=" * 40)
        logger.info("🏗️ STAGE 3: CREATING UNIFIED ENVIRONMENT")
        logger.info("=" * 40)
        unified_venv, install_status = create_unified_environment(all_dependencies, output_dir, args)
        if not unified_venv:
            logger.error("Failed to create unified virtual environment. Exiting.")
            return 1
        
        # Stage 4: Run tests for each repository
        logger.info("\n" + "=" * 40)
        logger.info("🧪 STAGE 4: RUNNING TESTS")
        logger.info("=" * 40)
        test_results = run_tests_parallel(repositories, output_dir, unified_venv, args)
        
        # Stage 5: Filter repositories that pass all tests or have no tests
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
        logger.error(f"Error in pipeline execution: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main()) 