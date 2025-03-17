#!/usr/bin/env python3
"""
Command-line tool for installing packages using UV.
"""

import argparse
import logging
import sys
import subprocess
from pathlib import Path

# Add parent directory to path to allow importing from repo2run
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from repo2run.utils.dependency_installer import DependencyInstaller
from repo2run.utils.logger import setup_logger


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description='Install a Python package with UV.')
    parser.add_argument('-p', '--package', required=True, type=str, help='The name of the package to install.')
    parser.add_argument('-v', '--version', type=str, default='', help='The version constraints of the package.')
    parser.add_argument('--dev', action='store_true', help='Install as a development dependency.')
    parser.add_argument('--venv', type=str, default='.venv', help='Path to the virtual environment.')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging.')
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logger(verbose=args.verbose)
    
    # Create full package name with version constraints
    if not args.version or len(args.version.strip()) == 0:
        full_name = args.package
    else:
        full_name = f"{args.package}{args.version}"
    
    # Get current working directory
    cwd = Path.cwd()
    
    try:
        # Check if uv is installed
        try:
            result = subprocess.run(
                ['uv', '--version'],
                check=False,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                logger.error("UV is not installed. Please install UV first.")
                return 1
        except Exception:
            logger.error("Failed to check if UV is installed.")
            return 1
        
        # Initialize project with uv if needed
        venv_path = Path(args.venv)
        if not venv_path.exists():
            logger.info(f"Initializing project with virtual environment at {venv_path}")
            try:
                result = subprocess.run(
                    ['uv', 'init', '--venv', str(venv_path)],
                    check=True,
                    capture_output=True,
                    text=True
                )
                logger.info(f"Project initialized with virtual environment at {venv_path}")
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to initialize project: {e.stderr}")
                return 1
        
        # Install the package using uv add
        cmd = ['uv', 'add', full_name]
        if args.dev:
            cmd.append('--dev')
        
        logger.info(f"Installing {full_name} using UV")
        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True
            )
            logger.info(f"The package {full_name} was installed successfully.")
            return 0
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to install the package {full_name}: {e.stderr}")
            return 1
    
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        return 1


if __name__ == '__main__':
    sys.exit(main()) 