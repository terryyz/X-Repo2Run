#!/usr/bin/env python3
"""
Command-line tool for installing packages using UV.
"""

import argparse
import logging
import sys
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
    
    # Create installer
    installer = DependencyInstaller(Path.cwd(), logger=logger)
    
    try:
        # Create virtual environment if it doesn't exist
        venv_path = Path(args.venv)
        if not venv_path.exists():
            logger.info(f"Creating virtual environment at {venv_path}")
            installer.create_virtual_environment(venv_path)
        
        # Install the package
        results = installer.install_requirements([full_name], venv_path)
        
        if results and results[0]['success']:
            logger.info(f"The package {full_name} was installed successfully.")
            return 0
        else:
            logger.error(f"Failed to install the package {full_name}")
            if results and 'error' in results[0]:
                logger.error(results[0]['error'])
            return 1
    
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        return 1


if __name__ == '__main__':
    sys.exit(main()) 