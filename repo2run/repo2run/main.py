#!/usr/bin/env python3
# Copyright (c) 2023-2024 Repo2Run Contributors

"""
Main entry point for Repo2Run.
This script handles the workflow of:
1. Cloning or using a local repository
2. Extracting and unifying requirements
3. Installing dependencies using UV
4. Running tests
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
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
    
    try:
        # Initialize repository
        repo_manager = RepoManager(workspace_dir=args.workspace_dir, logger=logger)
        
        if args.repo:
            full_name, sha = args.repo
            repo_path = repo_manager.clone_repository(full_name, sha)
            repo_name = repo_path.name
            logger.info(f"Cloned repository {full_name} at {sha}")
            # Store the temp directory for cleanup
            if args.workspace_dir is None:
                temp_dir = repo_path.parent
        else:
            local_path = Path(args.local).resolve()
            repo_path = repo_manager.setup_local_repository(local_path)
            repo_name = repo_path.name
            logger.info(f"Set up local repository from {local_path}")
        
        # Extract dependencies
        dependency_extractor = DependencyExtractor(repo_path, logger=logger)
        requirements = dependency_extractor.extract_all_requirements()
        unified_requirements = dependency_extractor.unify_requirements(requirements)
        
        # Save unified requirements
        requirements_path = output_dir / f"{repo_name}_requirements.txt"
        with open(requirements_path, 'w') as f:
            f.write('\n'.join(unified_requirements))
        logger.info(f"Saved unified requirements to {requirements_path}")
        
        # Create a project directory in the output folder
        project_dir = output_dir / repo_name
        project_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created project directory at {project_dir}")
        
        # Define paths for configuration files in the output directory
        requirements_in_path = project_dir / "requirements.in"
        compiled_requirements_path = project_dir / "requirements.txt"
        pyproject_path = project_dir / "pyproject.toml"
        venv_path = project_dir / '.venv'
        
        # Create a requirements.in file for uv pip compile
        with open(requirements_in_path, 'w') as f:
            f.write('\n'.join(unified_requirements))
        logger.info(f"Created requirements.in file at {requirements_in_path}")
        
        # Compile requirements with --resolution lowest to ensure compatibility with lower bounds
        logger.info("Compiling requirements with --resolution lowest")
        try:
            compiled_result = subprocess.run(
                ['uv', 'pip', 'compile', 'requirements.in', '--resolution', 'lowest', '--output-file', 'requirements.txt'],
                cwd=project_dir,
                check=True,
                capture_output=True,
                text=True
            )
            logger.info("Successfully compiled requirements with lowest resolution")
            
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
                
                logger.info(f"Parsed {len(exact_requirements)} exact requirements with lowest versions")
                
                # Use these exact requirements for installation
                unified_requirements = exact_requirements
            else:
                logger.warning("Compiled requirements.txt not found, using original requirements")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to compile requirements with lowest resolution: {e.stderr}")
            logger.warning("Falling back to original requirements")
        
        # Check if pyproject.toml already exists in the original repo
        original_pyproject_path = repo_path / "pyproject.toml"
        project_already_initialized = original_pyproject_path.exists()
        
        # If pyproject.toml exists in the original repo, copy it to the project directory
        if project_already_initialized:
            shutil.copy(original_pyproject_path, pyproject_path)
            logger.info(f"Copied existing pyproject.toml to {pyproject_path}")
        
        # Initialize project with uv
        logger.info("Initializing project with uv")
        
        try:
            # Install Python 3.8 using uv
            logger.info("Installing Python 3.8 using uv")
            result = subprocess.run(
                ['uv', 'python', 'install', '3.8'],
                cwd=project_dir,
                check=True,
                capture_output=True,
                text=True
            )
            logger.info(f"Python 3.8 installation result: {result.stdout}")
            
            # Pin Python version to 3.8 using uv python pin
            logger.info("Pinning Python version to 3.8")
            result = subprocess.run(
                ['uv', 'python', 'pin', '3.8'],
                cwd=project_dir,
                check=True,
                capture_output=True,
                text=True
            )
            logger.info(f"Python version pinning result: {result.stdout}")
            
            # Now initialize the project or create venv
            if project_already_initialized:
                logger.info("Project already initialized (pyproject.toml exists)")
                # Just create the venv with Python 3.8
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
            logger.info(f"Virtual environment created at {venv_path} with Python 3.8")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to initialize project: {e.stderr}")
            raise RuntimeError(f"Failed to initialize project: {e.stderr}")
        
        # Install dependencies using uv add
        logger.info(f"Installing {len(unified_requirements)} requirements using UV")
        installation_results = []
        
        # First, try to install all requirements at once from the compiled requirements.txt
        if compiled_requirements_path.exists():
            try:
                logger.info("Installing all requirements from compiled requirements.txt")
                cmd = ['uv', 'pip', 'install', '-r', 'requirements.txt', '--no-deps']
                
                result = subprocess.run(
                    cmd,
                    cwd=project_dir,
                    check=True,
                    capture_output=True,
                    text=True
                )
                
                logger.info("Successfully installed all requirements from compiled requirements.txt")
                
                # Mark all requirements as successfully installed
                for req in unified_requirements:
                    installation_results.append({
                        'package': req,
                        'success': True,
                        'output': "Installed via compiled requirements.txt",
                        'method': 'compiled'
                    })
            except subprocess.CalledProcessError as e:
                logger.warning(f"Failed to install from compiled requirements.txt: {e.stderr}")
                logger.warning("Falling back to individual package installation")
                # Continue with individual package installation below
        
        # If we don't have a compiled requirements file or the bulk installation failed,
        # install packages individually
        if not installation_results:
            for req in unified_requirements:
                try:
                    logger.info(f"Installing {req}")
                    
                    # Use uv add to install the requirement with --frozen flag to skip dependency resolution
                    cmd = ['uv', 'add', req, '--frozen', '--resolution lowest-direct']
                    
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
                        
                        logger.info(f"Successfully installed {req} with --frozen flag")
                    except subprocess.CalledProcessError as e:
                        logger.warning(f"Failed to install {req} with --frozen flag: {e.stderr}")
                        
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
                            
                            logger.info(f"Successfully installed {req} with --no-deps flag")
                        except subprocess.CalledProcessError as e2:
                            logger.warning(f"Failed to install {req} with --no-deps flag: {e2.stderr}")
                            
                            installation_results.append({
                                'package': req,
                                'success': False,
                                'error': f"Failed with --frozen: {e.stderr}\nFailed with --no-deps: {e2.stderr}"
                            })
                    
                except Exception as e:
                    logger.warning(f"Unexpected error installing {req}: {str(e)}")
                    
                    installation_results.append({
                        'package': req,
                        'success': False,
                        'error': str(e)
                    })
        
        # Save installation results
        installation_results_path = output_dir / f"{repo_name}_installation_results.json"
        with open(installation_results_path, 'w') as f:
            json.dump(installation_results, f, indent=2)
        logger.info(f"Saved installation results to {installation_results_path}")
        
        # Run tests using uv run
        # Copy necessary files from the original repo to the project directory for testing
        logger.info("Copying source files from repository to project directory for testing")
        try:
            # Copy Python files and directories, excluding .git, .venv, etc.
            for item in repo_path.glob('*'):
                if item.name not in ['.git', '.venv', '__pycache__', '.pytest_cache']:
                    if item.is_dir():
                        shutil.copytree(item, project_dir / item.name, dirs_exist_ok=True)
                    else:
                        shutil.copy(item, project_dir / item.name)
            logger.info("Source files copied successfully")
        except Exception as e:
            logger.warning(f"Error copying source files: {str(e)}")
        
        # Run tests in the project directory
        test_runner = TestRunner(project_dir, logger=logger)
        test_results = test_runner.run_tests()
        
        # Save test results
        test_results_path = output_dir / f"{repo_name}_test_results.json"
        with open(test_results_path, 'w') as f:
            json.dump(test_results, f, indent=2)
        logger.info(f"Saved test results to {test_results_path}")
        
        # Generate summary
        end_time = time.time()
        elapsed_time = end_time - start_time
        
        summary = {
            "repository": args.repo[0] if args.repo else str(args.local),
            "repository_name": repo_name,
            "elapsed_time": elapsed_time,
            "dependencies_found": len(unified_requirements),
            "dependencies_installed": sum(1 for r in installation_results if r["success"]),
            "tests_found": test_results["tests_found"],
            "tests_passed": test_results["tests_passed"],
            "status": "success" if test_results["status"] == "success" else "failure",
            "project_directory": str(project_dir)
        }
        
        summary_path = output_dir / f"{repo_name}_summary.json"
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2)
        
        logger.info(f"Process completed in {elapsed_time:.2f} seconds")
        logger.info(f"Summary saved to {summary_path}")
        logger.info(f"Project configured in {project_dir}")
        
        # No need to copy files as they're already in the output directory
        logger.info(f"All configuration and test files are available in {project_dir}")
        
        return 0
    
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}", exc_info=True)
        
        # Save error information
        error_path = output_dir / "error.txt"
        with open(error_path, 'w') as f:
            f.write(f"Error: {str(e)}\n")
        
        return 1
    
    finally:
        # Clean up temporary directory if it was created
        if temp_dir and args.workspace_dir is None:
            try:
                logger.info(f"Cleaning up temporary directory: {temp_dir}")
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Failed to clean up temporary directory: {str(e)}")


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