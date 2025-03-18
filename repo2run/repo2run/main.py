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
    repo2run --repo user/repo sha --output-dir output_path [--overwrite] [--verbose]
    repo2run --local path/to/repo --output-dir output_path [--overwrite] [--verbose]

    # Multiprocessing mode:
    repo2run --repo-list repos.txt --output-dir output_path [--overwrite] [--verbose] [--num-workers N]
    repo2run --local-list dirs.txt --output-dir output_path [--overwrite] [--verbose] [--num-workers N]

Options:
    --repo FULL_NAME SHA    The full name of the repository (e.g., user/repo) and SHA
    --local PATH            Local folder path to process
    --repo-list FILE       Text file containing list of repositories (format: user/repo sha)
    --local-list FILE      Text file containing list of local directories
    --output-dir DIR       Directory to store output files (default: output)
    --workspace-dir DIR    Directory to use as workspace (default: temporary directory)
    --timeout SECONDS      Timeout in seconds (default: 7200 - 2 hours)
    --verbose             Enable verbose logging
    --overwrite           Overwrite existing output directory if it exists
    --use-uv             Use UV for dependency management (default: False, use pip/venv)
    --num-workers N       Number of worker processes for parallel processing (default: number of CPU cores)
    --collect-only      Only collect test cases without installing dependencies or running tests
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
from pathlib import Path
from typing import List, Tuple, Optional

from repo2run.utils.repo_manager import RepoManager
from repo2run.utils.dependency_extractor import DependencyExtractor
from repo2run.utils.dependency_installer import DependencyInstaller
from repo2run.utils.test_runner import TestRunner
from repo2run.utils.logger import setup_logger


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
        '--num-workers',
        type=int,
        default=multiprocessing.cpu_count(),
        help='Number of worker processes for parallel processing (default: number of CPU cores)'
    )
    parser.add_argument(
        '--collect-only',
        action='store_true',
        help='Only collect test cases without installing dependencies or running tests'
    )
    
    return parser.parse_args()


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
    
    # Setup logging
    logger = setup_logger(verbose=args.verbose)
    logger.info("Starting Repo2Run")
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Ensure absolute path for output directory
    output_dir = output_dir.resolve()
    
    # Initialize results.jsonl file
    results_jsonl_path = output_dir / "results.jsonl"
    
    # Repository identifier (will be used as the key in the results.jsonl)
    repo_identifier = f"{repo_info[0]}_{repo_info[1]}" if repo_info else str(local_path)
    
    # Initialize result data structure with proper keys
    result_data = {
        "metadata": {
            "repository": repo_identifier,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "running"
        },
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
    
    # Original log entries (with timestamp and level)
    full_logs = []
    
    # Function to add log entries to the result data
    def add_log_entry(message, level="INFO", **kwargs):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = {
            "timestamp": timestamp,
            "level": level,
            "message": message,
            **kwargs
        }
        full_logs.append(log_entry)  # Store the full log object
        result_data["logs"].append(message)  # Only store the message string
        
        # Also log to regular logger with simplified format
        if level == "INFO":
            logger.info(message)
        elif level == "WARNING":
            logger.warning(message)
        elif level == "ERROR":
            logger.error(message)
    
    add_log_entry("Starting Repo2Run")
    add_log_entry(f"Using {'UV' if args.use_uv else 'pip/venv'} for dependency management")
    
    try:
        # Initialize repository
        repo_manager = RepoManager(workspace_dir=args.workspace_dir, logger=logger)
        
        if repo_info:
            full_name, sha = repo_info
            repo_path = repo_manager.clone_repository(full_name, sha)
            repo_name = repo_path.name
            add_log_entry(f"Cloned repository {full_name} at {sha}", repo_name=repo_name)
            result_data["repository_name"] = repo_name
        else:
            local_path = Path(local_path).resolve()
            repo_path = repo_manager.setup_local_repository(local_path)
            repo_name = repo_path.name
            add_log_entry(f"Set up local repository from {local_path}", repo_name=repo_name)
            result_data["repository_name"] = repo_name
        
        # Create a project directory in the output folder
        project_dir = output_dir / repo_identifier
        
        # Check if project directory already exists
        if project_dir.exists():
            if args.overwrite:
                add_log_entry(f"Project directory {project_dir} already exists. Overwriting as requested.", level="WARNING")
                # Remove the existing directory
                shutil.rmtree(project_dir)
            else:
                add_log_entry(f"Project directory {project_dir} already exists. Use --overwrite to overwrite.", level="ERROR")
                result_data["status"] = "error"
                result_data["error"] = "Project directory already exists"
                # Write the result to results.jsonl
                with open(results_jsonl_path, "a") as f:
                    f.write(json.dumps(result_data) + "\n")
                return 1
        
        # Create the project directory
        project_dir.mkdir(parents=True, exist_ok=False)
        add_log_entry(f"Created project directory at {project_dir}")
        result_data["project_directory"] = str(project_dir)
        
        # Copy the entire repository to the project directory
        add_log_entry(f"Copying repository from {repo_path} to {project_dir}")
        try:
            # Ensure the project directory exists
            project_dir.mkdir(parents=True, exist_ok=True)
            
            # List all items in the source repository
            source_items = list(os.listdir(repo_path))
            add_log_entry(f"Found {len(source_items)} items to copy: {source_items}")
            
            for item in source_items:
                src = repo_path / item
                dst = project_dir / item
                
                # Log each item being copied
                add_log_entry(f"Copying {src} to {dst}")
                
                try:
                    # Remove existing destination if it exists
                    if dst.exists():
                        if dst.is_dir():
                            shutil.rmtree(dst)
                        else:
                            dst.unlink()
                    
                    # Copy item
                    if src.is_dir():
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)
                    
                    add_log_entry(f"Successfully copied {item}")
                
                except Exception as copy_error:
                    add_log_entry(f"Error copying {item}: {copy_error}", level="WARNING")
            
            # Verify copy
            copied_items = list(os.listdir(project_dir))
            add_log_entry(f"Copied {len(copied_items)} items to project directory: {copied_items}")
            
            # Update repo_path to point to the new location in the output directory
            repo_path = project_dir
        
        except Exception as e:
            add_log_entry(f"Critical error during repository copy: {e}", level="ERROR")
            result_data["status"] = "error"
            result_data["error"] = f"Failed to copy repository: {e}"
            
            # Write the result to results.jsonl
            with open(results_jsonl_path, "a") as f:
                f.write(json.dumps(result_data) + "\n")
            
            raise RuntimeError(f"Failed to copy repository: {e}")
        
        # Extract dependencies
        dependency_extractor = DependencyExtractor(repo_path, logger=logger)
        requirements = dependency_extractor.extract_all_requirements()
        unified_requirements = dependency_extractor.unify_requirements(requirements)
        result_data["dependencies"]["found"] = len(unified_requirements)
        result_data["dependencies"]["details"] = unified_requirements
        
        add_log_entry(f"Extracted {len(unified_requirements)} requirements")
        
        # Define paths for configuration files in the output directory
        requirements_in_path = project_dir / "requirements.in"
        compiled_requirements_path = project_dir / "requirements.txt"
        pyproject_path = project_dir / "pyproject.toml"
        venv_path = project_dir / '.venv'
        
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
                    cwd=project_dir,
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
        original_pyproject_path = repo_path / "pyproject.toml"
        project_already_initialized = original_pyproject_path.exists()
        
        # If pyproject.toml exists in the original repo, copy it to the project directory
        if project_already_initialized:
            shutil.copy(original_pyproject_path, pyproject_path)
            add_log_entry(f"Copied existing pyproject.toml to {pyproject_path}")
        
        # Initialize project
        if args.use_uv:
            add_log_entry("Initializing project with uv")
            
            try:
                # Install Python 3.10 using uv
                add_log_entry("Installing Python 3.10 using uv")
                result = subprocess.run(
                    ['uv', 'python', 'install', '3.10'],
                    cwd=project_dir,
                    check=True,
                    capture_output=True,
                    text=True
                )
                add_log_entry(f"Python 3.10 installation result: {result.stdout}")
                
                # Pin Python version to 3.10 using uv python pin
                add_log_entry("Pinning Python version to 3.10")
                result = subprocess.run(
                    ['uv', 'python', 'pin', '3.10'],
                    cwd=project_dir,
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
                        cwd=project_dir,
                        check=True,
                        capture_output=True,
                        text=True
                    )
                else:
                    # Initialize project with uv init
                    result = subprocess.run(
                        ['uv', 'init'],
                        cwd=project_dir,
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
                        cwd=project_dir,
                        check=True,
                        capture_output=True,
                        text=True
                    )
                    add_log_entry(f"Successfully installed package in development mode: {result.stdout.strip()}")
                except subprocess.CalledProcessError as e:
                    add_log_entry(f"Failed to install Cython or package in development mode: {e.stderr}", level="WARNING")
                    add_log_entry("Continuing without development mode installation", level="WARNING")
                
                # Install dependencies
                dependency_installer = DependencyInstaller(project_dir, use_uv=args.use_uv, logger=logger)
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
                    result_data["status"] = "failure"
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
                                cwd=project_dir,
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
        
        # If collect-only mode is enabled, only collect tests without running them
        if args.collect_only:
            add_log_entry("Running in collect-only mode", level="INFO")
            
            # Run test collection
            test_runner = TestRunner(project_dir, venv_path=venv_path, use_uv=args.use_uv, logger=logger)
            
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
                result_data["status"] = "failure"
                result_data["error"] = str(e)
                
                # Write the result to results.jsonl
                with open(results_jsonl_path, "a") as f:
                    f.write(json.dumps(result_data) + "\n")
                
                return 1
        
        # Run tests
        # Copy necessary files from the original repo to the project directory for testing
        add_log_entry("Copying source files from repository to project directory for testing")
        try:
            # Copy Python files and directories, excluding .git, .venv, etc.
            for item in repo_path.glob('*'):
                if item.name not in ['.git', '.venv', '__pycache__', '.pytest_cache']:
                    if item.is_dir():
                        shutil.copytree(item, project_dir / item.name, dirs_exist_ok=True)
                    else:
                        shutil.copy(item, project_dir / item.name)
            add_log_entry("Source files copied successfully")
        except Exception as e:
            add_log_entry(f"Error copying source files: {str(e)}", level="WARNING")
        
        # Run tests in the project directory
        test_runner = TestRunner(project_dir, venv_path=venv_path, use_uv=args.use_uv, logger=logger)
        add_log_entry("Looking for tests in the project's code (excluding virtual environment)")
        
        # Check for project-specific tests first
        test_files = test_runner.find_tests()
        
        if not test_files:
            add_log_entry("No project-specific tests found. The project may not have tests.", level="WARNING")
            result_data["tests"]["found"] = 0
            result_data["tests"]["passed"] = 0
            result_data["tests"]["failed"] = 0
            result_data["tests"]["skipped"] = 0
            
            add_log_entry("Setting status to success since no tests were found")
            result_data["status"] = "success"
        else:
            add_log_entry(f"Found {len(test_files)} test files in the project")
            
            # Run test discovery
            test_results = test_runner.run_tests()
            
            # Store test results in the result data
            result_data["tests"]["found"] = test_results["tests_found"]
            result_data["tests"]["passed"] = test_results["tests_passed"]
            result_data["tests"]["failed"] = test_results["tests_failed"]
            result_data["tests"]["skipped"] = test_results["tests_skipped"]
            result_data["tests"]["details"] = test_results["test_results"]
            
            add_log_entry(f"Test results: found={test_results['tests_found']}, passed={test_results['tests_passed']}, failed={test_results['tests_failed']}, skipped={test_results['tests_skipped']}")
            
            # Fix the status determination
            if test_results.get("status") == "error":
                add_log_entry("Setting status to failure due to test error")
                result_data["status"] = "failure"
            elif test_results["tests_failed"] > 0:
                add_log_entry(f"Setting status to failure due to failed tests: {test_results['tests_failed']}")
                result_data["status"] = "failure"
            elif result_data["tests"]["found"] > 0 and result_data["tests"]["passed"] == 0:
                add_log_entry("Setting status to failure because tests were found but none passed")
                result_data["status"] = "failure"
            else:
                add_log_entry("Setting status to success")
                result_data["status"] = "success"
        
        # Generate summary
        end_time = time.time()
        elapsed_time = end_time - start_time
        
        # Update result data with summary information
        result_data["execution"]["elapsed_time"] = elapsed_time
        result_data["dependencies"]["installed"] = sum(1 for r in installation_results if r["success"])
        
        # Log the current test counts before final update
        add_log_entry(f"Test counts before final update: found={result_data['tests']['found']}, passed={result_data['tests']['passed']}, failed={result_data['tests']['failed']}, skipped={result_data['tests']['skipped']}")
        
        add_log_entry(f"Process completed in {elapsed_time:.2f} seconds")
        add_log_entry(f"Project configured in {project_dir}")
        
        # Write the final result to results.jsonl
        with open(results_jsonl_path, "a") as f:
            f.write(json.dumps(result_data) + "\n")
        
        add_log_entry(f"Results written to {results_jsonl_path}")
        
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
        
        return 1


def process_repo_list(args: argparse.Namespace) -> int:
    """Process a list of repositories in parallel.
    
    Args:
        args: Command line arguments
    
    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
    # Read the repository list file
    with open(args.repo_list, 'r') as f:
        repo_lines = f.readlines()
    
    # Parse repository information
    repo_infos = []
    for line in repo_lines:
        line = line.strip()
        if line and not line.startswith('#'):
            try:
                full_name, sha = line.split()
                repo_infos.append((full_name, sha))
            except ValueError:
                print(f"Invalid line in repository list: {line}")
                return 1
    
    if not repo_infos:
        print("No valid repositories found in the list")
        return 1
    
    # Create a pool of worker processes
    with multiprocessing.Pool(processes=args.num_workers) as pool:
        # Process repositories in parallel
        results = pool.starmap(
            process_single_repo,
            [(args, repo_info, None) for repo_info in repo_infos]
        )
    
    # Check if any process failed
    return 1 if any(result != 0 for result in results) else 0


def process_local_list(args: argparse.Namespace) -> int:
    """Process a list of local directories in parallel.
    
    Args:
        args: Command line arguments
    
    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
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
        print("No valid directories found in the list")
        return 1
    
    # Create a pool of worker processes
    with multiprocessing.Pool(processes=args.num_workers) as pool:
        # Process directories in parallel
        results = pool.starmap(
            process_single_repo,
            [(args, None, dir_path) for dir_path in dir_paths]
        )
    
    # Check if any process failed
    return 1 if any(result != 0 for result in results) else 0


def main():
    """Main entry point for the application."""
    # Parse arguments
    args = parse_arguments()
    
    # Process based on the mode
    if args.repo_list:
        return process_repo_list(args)
    elif args.local_list:
        return process_local_list(args)
    else:
        # Single repository/directory mode
        return process_single_repo(args, args.repo if args.repo else None, args.local if args.local else None)


if __name__ == "__main__":
    # Set up timeout
    def timeout_handler():
        time.sleep(7200)  # Default 2 hour timeout
        print("Timeout reached. Exiting.")
        sys.exit(1)
    
    # Clean up any dangling Docker images
    try:
        subprocess.run(
            'docker rmi $(docker images --filter "dangling=true" -q) > /dev/null 2>&1',
            shell=True, check=False
        )
    except Exception:
        print("Failed to clean up dangling Docker images")
    
    sys.exit(main()) 