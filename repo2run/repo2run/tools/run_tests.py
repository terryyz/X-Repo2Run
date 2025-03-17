#!/usr/bin/env python3
"""
Command-line tool for running tests.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add parent directory to path to allow importing from repo2run
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from repo2run.utils.test_runner import TestRunner
from repo2run.utils.logger import setup_logger


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description='Run tests in a repository.')
    parser.add_argument('--repo-path', type=str, default='.', help='Path to the repository.')
    parser.add_argument('--venv', type=str, default='.venv', help='Path to the virtual environment.')
    parser.add_argument('--output', type=str, help='Path to save test results as JSON.')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging.')
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logger(verbose=args.verbose)
    
    # Create test runner
    repo_path = Path(args.repo_path).resolve()
    venv_path = Path(args.venv)
    
    logger.info(f"Running tests in repository: {repo_path}")
    logger.info(f"Using virtual environment: {venv_path}")
    
    test_runner = TestRunner(repo_path, venv_path, logger=logger)
    
    try:
        # Run tests
        results = test_runner.run_tests()
        
        # Print summary
        print(f"\nTest Results: {results['message']}")
        print(f"Tests Found: {results['tests_found']}")
        print(f"Tests Passed: {results['tests_passed']}")
        print(f"Tests Failed: {results['tests_failed']}")
        print(f"Tests Skipped: {results['tests_skipped']}")
        print(f"Status: {results['status']}")
        
        # Save results if output path is provided
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, 'w') as f:
                json.dump(results, f, indent=2)
            
            logger.info(f"Test results saved to {output_path}")
        
        return 0 if results['status'] == 'success' else 1
    
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        return 1


if __name__ == '__main__':
    sys.exit(main()) 