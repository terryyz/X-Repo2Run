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
        
        # Check if pyproject.toml already exists
        pyproject_path = repo_path / "pyproject.toml"
        project_already_initialized = pyproject_path.exists()
        
        # Initialize project with uv
        logger.info("Initializing project with uv")
        venv_path = repo_path / '.venv'
        
        try:
            if project_already_initialized:
                logger.info("Project already initialized (pyproject.toml exists)")
                # Just create the venv without initializing the project
                result = subprocess.run(
                    ['uv', 'venv', str(venv_path)],
                    cwd=repo_path,
                    check=True,
                    capture_output=True,
                    text=True
                )
            else:
                result = subprocess.run(
                    ['uv', 'init'],
                    cwd=repo_path,
                    check=True,
                    capture_output=True,
                    text=True
                )
            logger.info(f"Virtual environment created at {venv_path}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to initialize project: {e.stderr}")
            raise RuntimeError(f"Failed to initialize project: {e.stderr}")
        
        # Install dependencies using uv add
        logger.info(f"Installing {len(unified_requirements)} requirements using UV")
        installation_results = []
        
        for req in unified_requirements:
            try:
                logger.info(f"Installing {req}")
                
                # Use uv add to install the requirement with --frozen flag to skip dependency resolution
                cmd = ['uv', 'add', req, '--frozen']
                
                # First try with --frozen flag
                try:
                    result = subprocess.run(
                        cmd,
                        cwd=repo_path,
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
                            cwd=repo_path,
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
        test_runner = TestRunner(repo_path, logger=logger)
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
            "status": "success" if test_results["status"] == "success" else "failure"
        }
        
        summary_path = output_dir / f"{repo_name}_summary.json"
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2)
        
        logger.info(f"Process completed in {elapsed_time:.2f} seconds")
        logger.info(f"Summary saved to {summary_path}")
        
        # Copy any important files from the repo to the output directory
        try:
            # Copy pyproject.toml if it exists
            if pyproject_path.exists():
                shutil.copy(pyproject_path, output_dir / f"{repo_name}_pyproject.toml")
                logger.info(f"Copied pyproject.toml to {output_dir / f'{repo_name}_pyproject.toml'}")
            
            # Copy any test files found
            test_files_dir = output_dir / f"{repo_name}_test_files"
            test_files_dir.mkdir(exist_ok=True)
            
            # Find test files
            test_files = []
            test_files.extend(repo_path.glob("tests/**/*.py"))
            test_files.extend(repo_path.glob("test/**/*.py"))
            test_files.extend(repo_path.glob("test_*.py"))
            test_files.extend(repo_path.glob("*_test.py"))
            
            for test_file in test_files:
                rel_path = test_file.relative_to(repo_path)
                dest_path = test_files_dir / rel_path
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(test_file, dest_path)
            
            if test_files:
                logger.info(f"Copied {len(test_files)} test files to {test_files_dir}")
        except Exception as e:
            logger.warning(f"Failed to copy some files: {str(e)}")
        
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