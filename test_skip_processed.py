#!/usr/bin/env python3
"""
Test script to verify the --extract-dep and --skip-processed functionality.

This script:
1. Creates a temporary directory with test repositories
2. Runs extract-dep on them
3. Runs extract-dep again with skip-processed
4. Verifies the correct repositories were skipped

Usage:
    python test_skip_processed.py
"""

import os
import sys
import tempfile
import shutil
import subprocess
import json
from pathlib import Path
import logging
import time

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

def create_test_repo(base_dir, name, packages):
    """Create a test repository with specified packages."""
    repo_dir = base_dir / name
    repo_dir.mkdir(parents=True, exist_ok=True)
    
    # Create a requirements.txt file
    with open(repo_dir / "requirements.txt", "w") as f:
        f.write("\n".join(packages))
    
    # Create a dummy test file
    with open(repo_dir / "test_dummy.py", "w") as f:
        f.write("""
import unittest

class TestDummy(unittest.TestCase):
    def test_pass(self):
        self.assertTrue(True)

if __name__ == '__main__':
    unittest.main()
""")
    
    return repo_dir

def main():
    """Run the test script."""
    logger.info("Starting test of --extract-dep and --skip-processed functionality")
    
    # Create a temporary directory for our test
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        logger.info(f"Created temporary directory: {temp_path}")
        
        # Create test repositories
        repos = {
            "repo1": ["numpy", "pandas", "matplotlib"],
            "repo2": ["requests", "beautifulsoup4", "lxml"],
            "repo3": ["flask", "sqlalchemy", "alembic"]
        }
        
        repo_dirs = {}
        for name, packages in repos.items():
            repo_dirs[name] = create_test_repo(temp_path, name, packages)
        
        # Create a list of repositories
        repo_list_file = temp_path / "repos.txt"
        with open(repo_list_file, "w") as f:
            for name, path in repo_dirs.items():
                f.write(f"{path}\n")
        
        # Create output directory
        output_dir = temp_path / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Run extract-dep on all repositories
        logger.info("Running extract-dep on all repositories...")
        cmd = [
            sys.executable, "-m", "repo2run",
            "--global",
            "--local-list", str(repo_list_file),
            "--output-dir", str(output_dir),
            "--extract-dep",
            "--verbose"
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info("First extract-dep run completed successfully")
        except subprocess.CalledProcessError as e:
            logger.error(f"First extract-dep run failed: {e.stderr}")
            return 1
        
        # Check repo_req.jsonl file
        repo_req_jsonl = output_dir / "repo_req.jsonl"
        if not repo_req_jsonl.exists():
            logger.error(f"repo_req.jsonl not found at {repo_req_jsonl}")
            return 1
        
        # Read the repositories in repo_req.jsonl
        processed_repos = set()
        with open(repo_req_jsonl, "r") as f:
            for line in f:
                try:
                    record = json.loads(line.strip())
                    if "repository" in record:
                        processed_repos.add(record["repository"])
                except json.JSONDecodeError:
                    continue
        
        logger.info(f"Found {len(processed_repos)} processed repositories in repo_req.jsonl")
        
        # Create a new repository
        new_repo_name = "repo4"
        new_repo_path = create_test_repo(temp_path, new_repo_name, ["pytest", "pytest-cov", "coverage"])
        repo_dirs[new_repo_name] = new_repo_path
        
        # Update the repository list
        with open(repo_list_file, "w") as f:
            for name, path in repo_dirs.items():
                f.write(f"{path}\n")
        
        # Run extract-dep again with skip-processed
        logger.info("Running extract-dep again with skip-processed...")
        cmd = [
            sys.executable, "-m", "repo2run",
            "--global",
            "--local-list", str(repo_list_file),
            "--output-dir", str(output_dir),
            "--extract-dep",
            "--skip-processed",
            "--verbose"
        ]
        
        process = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info("Second extract-dep run completed successfully")
        
        # Check output for skipped repositories
        output = process.stdout + process.stderr
        logger.info("Checking output for skipped repositories...")
        
        # Read the updated repo_req.jsonl
        new_processed_repos = set()
        with open(repo_req_jsonl, "r") as f:
            for line in f:
                try:
                    record = json.loads(line.strip())
                    if "repository" in record:
                        new_processed_repos.add(record["repository"])
                except json.JSONDecodeError:
                    continue
        
        logger.info(f"Found {len(new_processed_repos)} processed repositories after second run")
        
        # Check that the original repositories were skipped and only the new one was processed
        skipped_count = 0
        for repo_name in ["repo1", "repo2", "repo3"]:
            repo_path = str(repo_dirs[repo_name].resolve())
            if f"Skipping already processed repository: {repo_path}" in output:
                skipped_count += 1
                logger.info(f"Repository {repo_name} was correctly skipped")
            else:
                logger.warning(f"Repository {repo_name} was not skipped as expected")
        
        # Check if the new repository was processed
        new_repo_path = str(repo_dirs[new_repo_name].resolve())
        new_repo_processed = new_repo_path in new_processed_repos
        if new_repo_processed:
            logger.info(f"New repository {new_repo_name} was correctly processed")
        else:
            logger.error(f"New repository {new_repo_name} was not processed")
        
        # Check counts
        if skipped_count == 3 and new_repo_processed:
            logger.info("TEST PASSED: All repositories were handled correctly")
            return 0
        else:
            logger.error(f"TEST FAILED: {skipped_count}/3 repositories skipped, new repo processed: {new_repo_processed}")
            return 1

if __name__ == "__main__":
    sys.exit(main()) 