#!/usr/bin/env python3
# Copyright (c) 2023-2024 Repo2Run Contributors

"""
Main entry point for Repo2Run.
This script handles the workflow of:
1. Cloning or using a local repository
2. Extracting and unifying requirements
3. Installing dependencies using UV
4. Running tests

Usage:
    repo2run --repo user/repo sha --output-dir output_path [--overwrite] [--verbose]
    repo2run --local path/to/repo --output-dir output_path [--overwrite] [--verbose]

Options:
    --repo FULL_NAME SHA    The full name of the repository (e.g., user/repo) and SHA
    --local PATH            Local folder path to process
    --output-dir DIR        Directory to store output files (default: output)
    --workspace-dir DIR     Directory to use as workspace (default: temporary directory)
    --timeout SECONDS       Timeout in seconds (default: 7200 - 2 hours)
    --verbose               Enable verbose logging
    --overwrite             Overwrite existing output directory if it exists
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import datetime
from pathlib import Path

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
    
    return parser.parse_args()


def main():
    """Main entry point for the application."""
    start_time = time.time()
    temp_dir = None
    
    # Parse arguments
    args = parse_arguments()
    
    # Setup logging
    logger = setup_logger(verbose=args.verbose)
    logger.info("Starting Repo2Run")
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize results.jsonl file
    results_jsonl_path = output_dir / "results.jsonl"
    
    # Repository identifier (will be used as the key in the results.jsonl)
    repo_identifier = args.repo[0] if args.repo else str(args.local)
    
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
            "timeout": args.timeout
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
    
    # Function to add log entries to the result data
    def add_log_entry(message, level="INFO", **kwargs):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = {
            "timestamp": timestamp,
            "level": level,
            "message": message,
            **kwargs
        }
        result_data["logs"].append(log_entry)
        
        # Also log to regular logger
        if level == "INFO":
            logger.info(message)
        elif level == "WARNING":
            logger.warning(message)
        elif level == "ERROR":
            logger.error(message)
    
    add_log_entry("Starting Repo2Run")
    
    try:
        # Initialize repository
        repo_manager = RepoManager(workspace_dir=args.workspace_dir, logger=logger)
        
        if args.repo:
            full_name, sha = args.repo
            repo_path = repo_manager.clone_repository(full_name, sha)
            repo_name = repo_path.name
            add_log_entry(f"Cloned repository {full_name} at {sha}", repo_name=repo_name)
            result_data["repository_name"] = repo_name
            # Store the temp directory for cleanup
            if args.workspace_dir is None:
                temp_dir = repo_path.parent
        else:
            local_path = Path(args.local).resolve()
            repo_path = repo_manager.setup_local_repository(local_path)
            repo_name = repo_path.name
            add_log_entry(f"Set up local repository from {local_path}", repo_name=repo_name)
            result_data["repository_name"] = repo_name
        
        # Create a project directory in the output folder
        project_dir = output_dir / repo_name
        
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
        
        # Create a requirements.in file for uv pip compile
        with open(requirements_in_path, 'w') as f:
            f.write('\n'.join(unified_requirements))
        add_log_entry(f"Created requirements.in file at {requirements_in_path}")
        
        # Compile requirements with --resolution lowest to ensure compatibility with lower bounds
        add_log_entry("Compiling requirements with --resolution lowest")
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
        
        # Check if pyproject.toml already exists in the original repo
        original_pyproject_path = repo_path / "pyproject.toml"
        project_already_initialized = original_pyproject_path.exists()
        
        # If pyproject.toml exists in the original repo, copy it to the project directory
        if project_already_initialized:
            shutil.copy(original_pyproject_path, pyproject_path)
            add_log_entry(f"Copied existing pyproject.toml to {pyproject_path}")
        
        # Initialize project with uv
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
            
        except subprocess.CalledProcessError as e:
            add_log_entry(f"Failed to initialize project: {e.stderr}", level="ERROR")
            result_data["status"] = "error"
            result_data["error"] = f"Failed to initialize project: {e.stderr}"
            # Write the result to results.jsonl
            with open(results_jsonl_path, "a") as f:
                f.write(json.dumps(result_data) + "\n")
            raise RuntimeError(f"Failed to initialize project: {e.stderr}")
        
        # Install dependencies using uv add
        add_log_entry(f"Installing {len(unified_requirements)} requirements using UV")
        installation_results = []
        
        # First, try to install all requirements at once from the compiled requirements.txt
        if compiled_requirements_path.exists():
            try:
                add_log_entry("Installing all requirements from compiled requirements.txt")
                cmd = ['uv', 'pip', 'install', '-r', 'requirements.txt', '--no-deps']
                
                result = subprocess.run(
                    cmd,
                    cwd=project_dir,
                    check=True,
                    capture_output=True,
                    text=True
                )
                
                add_log_entry("Successfully installed all requirements from compiled requirements.txt")
                
                # Mark all requirements as successfully installed
                for req in unified_requirements:
                    installation_results.append({
                        'package': req,
                        'success': True,
                        'output': "Installed via compiled requirements.txt",
                        'method': 'compiled'
                    })
            except subprocess.CalledProcessError as e:
                add_log_entry(f"Failed to install from compiled requirements.txt: {e.stderr}", level="WARNING")
                add_log_entry("Falling back to individual package installation", level="WARNING")
                # Continue with individual package installation below
        
        # If we don't have a compiled requirements file or the bulk installation failed,
        # install packages individually
        if not installation_results:
            for req in unified_requirements:
                try:
                    add_log_entry(f"Installing {req}")
                    
                    # Use uv add to install the requirement with --frozen flag to skip dependency resolution
                    cmd = ['uv', 'add', req, '--frozen', '--resolution', 'lowest-direct']
                    
                    # First try with --frozen flag
                    try:
                        result = subprocess.run(
                            cmd,
                            cwd=project_dir,
                            check=True,
                            capture_output=True,
                            text=True
                        )
                        
                        installation_results.append({
                            'package': req,
                            'success': True,
                            'output': result.stdout,
                            'method': 'frozen'
                        })
                        
                        add_log_entry(f"Successfully installed {req} with --frozen flag")
                    except subprocess.CalledProcessError as e:
                        add_log_entry(f"Failed to install {req} with --frozen flag: {e.stderr}", level="WARNING")
                        
                        # If it fails with --frozen, try with additional flags
                        try:
                            # Try with --no-deps as an alternative
                            cmd_alt = ['uv', 'add', req, '--no-deps']
                            result = subprocess.run(
                                cmd_alt,
                                cwd=project_dir,
                                check=True,
                                capture_output=True,
                                text=True
                            )
                            
                            installation_results.append({
                                'package': req,
                                'success': True,
                                'output': result.stdout,
                                'method': 'no-deps'
                            })
                            
                            add_log_entry(f"Successfully installed {req} with --no-deps flag")
                        except subprocess.CalledProcessError as e2:
                            add_log_entry(f"Failed to install {req} with --no-deps flag: {e2.stderr}", level="WARNING")
                            
                            installation_results.append({
                                'package': req,
                                'success': False,
                                'error': f"Failed with --frozen: {e.stderr}\nFailed with --no-deps: {e2.stderr}"
                            })
                    
                except Exception as e:
                    add_log_entry(f"Unexpected error installing {req}: {str(e)}", level="WARNING")
                    
                    installation_results.append({
                        'package': req,
                        'success': False,
                        'error': str(e)
                    })
        
        # Store installation results in the result data
        result_data["installation_results"] = installation_results
        result_data["dependencies"]["installed"] = sum(1 for r in installation_results if r["success"])
        
        # Run tests using uv run
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
        test_runner = TestRunner(project_dir, logger=logger)
        test_results = test_runner.run_tests()
        
        # Store test results in the result data
        result_data["tests"]["found"] = test_results["tests_found"]
        result_data["tests"]["passed"] = test_results["tests_passed"]
        result_data["tests"]["failed"] = test_results["tests_failed"]
        result_data["tests"]["skipped"] = test_results["tests_skipped"]
        result_data["tests"]["details"] = test_results["test_results"]
        
        # If no tests were found but test files exist, update the count
        if test_results["tests_found"] == 0:
            # Get the number of test files
            test_files = test_runner.find_tests()
            if test_files:
                num_test_files = len(test_files)
                add_log_entry(f"No tests were collected due to dependency issues, but {num_test_files} test files were found", level="WARNING")
                result_data["tests"]["found"] = num_test_files
                result_data["tests"]["failed"] = num_test_files  # Mark all as failed since they couldn't run
                
                # Add test files to details
                for test_file in test_files:
                    result_data["tests"]["details"].append({
                        "name": str(test_file.relative_to(project_dir)),
                        "status": "error",
                        "message": "Could not run due to dependency issues"
                    })
        
        # Generate summary
        end_time = time.time()
        elapsed_time = end_time - start_time
        
        # Update result data with summary information
        result_data["execution"]["elapsed_time"] = elapsed_time
        result_data["dependencies"]["installed"] = sum(1 for r in installation_results if r["success"])
        result_data["tests"]["found"] = test_results["tests_found"]
        result_data["tests"]["passed"] = test_results["tests_passed"]
        result_data["tests"]["failed"] = test_results["tests_failed"]
        result_data["tests"]["skipped"] = test_results["tests_skipped"]
        
        # Fix the status determination
        if test_results.get("status") == "error" or test_results["tests_failed"] > 0:
            result_data["status"] = "failure"
        elif result_data["tests"]["found"] > 0 and result_data["tests"]["passed"] == 0:
            # If tests were found but none passed (likely due to dependency issues)
            result_data["status"] = "failure"
        else:
            result_data["status"] = "success"
        
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
    
    finally:
        # Clean up temporary directory if it was created
        if temp_dir and args.workspace_dir is None:
            try:
                add_log_entry(f"Cleaning up temporary directory: {temp_dir}")
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as e:
                add_log_entry(f"Failed to clean up temporary directory: {str(e)}", level="WARNING")


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