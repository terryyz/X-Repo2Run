#!/usr/bin/env python3
"""
Command-line tool for extracting requirements from a repository.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add parent directory to path to allow importing from repo2run
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from repo2run.utils.dependency_extractor import DependencyExtractor
from repo2run.utils.logger import setup_logger


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description='Extract requirements from a repository.')
    parser.add_argument('--repo-path', type=str, default='.', help='Path to the repository.')
    parser.add_argument('--output', type=str, help='Path to save unified requirements.')
    parser.add_argument('--json', action='store_true', help='Output in JSON format.')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging.')
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logger(verbose=args.verbose)
    
    # Create dependency extractor
    repo_path = Path(args.repo_path).resolve()
    
    logger.info(f"Extracting requirements from repository: {repo_path}")
    
    extractor = DependencyExtractor(repo_path, logger=logger)
    
    try:
        # Extract requirements
        requirements = extractor.extract_all_requirements()
        
        # Unify requirements
        unified_requirements = extractor.unify_requirements(requirements)
        
        # Print summary
        print(f"\nRequirements Summary:")
        print(f"Sources Found: {len(requirements)}")
        print(f"Unified Requirements: {len(unified_requirements)}")
        
        # Print sources
        if args.verbose:
            print("\nSources:")
            for source, reqs in requirements.items():
                print(f"  {source}: {len(reqs)} requirements")
        
        # Print unified requirements
        print("\nUnified Requirements:")
        for req in unified_requirements:
            print(f"  {req}")
        
        # Save results if output path is provided
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            if args.json:
                # Save as JSON
                with open(output_path, 'w') as f:
                    json.dump({
                        'sources': requirements,
                        'unified': unified_requirements
                    }, f, indent=2)
            else:
                # Save as text
                with open(output_path, 'w') as f:
                    f.write('\n'.join(unified_requirements))
            
            logger.info(f"Requirements saved to {output_path}")
        
        return 0
    
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        return 1


if __name__ == '__main__':
    sys.exit(main()) 