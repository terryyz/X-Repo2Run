#!/usr/bin/env python3
"""
Script to copy repositories from HDFS to local directory.
Each line in the input JSONL file contains a repository path.
The script copies each repository from HDFS to the local directory.
"""

import json
import os
import subprocess
import sys
import argparse
import time
import multiprocessing
import concurrent.futures
from tqdm import tqdm
from collections import Counter

# HDFS base path
HDFS_BASE_PATH = "hdfs://harunava/home/byte_data_seed_azureb_tteng/user/codeai/unzip_code_repo_batch"


def parse_args():
    """Parse command line arguments."""
    # Get CPU count for default worker count
    cpu_count = multiprocessing.cpu_count()
    
    parser = argparse.ArgumentParser(description="Copy repositories from HDFS to local directory")
    parser.add_argument(
        "jsonl_files",
        nargs='+',
        help="Path(s) to the JSONL file(s) containing repository information"
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Local directory to copy repositories to (default: current directory)"
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip repositories that already exist locally"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not perform actual copying, just simulate the process"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print verbose output"
    )
    parser.add_argument(
        "--max-repos",
        type=int,
        default=None,
        help="Maximum number of repositories to process"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=cpu_count,
        help=f"Number of parallel workers (default: {cpu_count} - all available CPU cores)"
    )
    return parser.parse_args()


def read_repositories(jsonl_files):
    """Read repository paths from the JSONL files."""
    repositories = []
    total_lines = 0
    valid_lines = 0
    
    for jsonl_file in jsonl_files:
        file_count = 0
        try:
            with open(jsonl_file, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    total_lines += 1
                    try:
                        data = json.loads(line.strip())
                        if "repository" in data:
                            repositories.append(data["repository"])
                            file_count += 1
                            valid_lines += 1
                    except json.JSONDecodeError:
                        print(f"Warning: Failed to parse line {line_num} in {jsonl_file}: {line.strip()[:100]}...")
            print(f"Found {file_count} repositories in {jsonl_file}")
        except Exception as e:
            print(f"Error reading file {jsonl_file}: {str(e)}")
    
    # Find and report duplicates
    repo_counts = Counter(repositories)
    duplicates = {repo: count for repo, count in repo_counts.items() if count > 1}
    if duplicates:
        print(f"Found {len(duplicates)} duplicate repositories:")
        for repo, count in sorted(duplicates.items(), key=lambda x: x[1], reverse=True)[:5]:
            print(f"  - {repo}: {count} occurrences")
        if len(duplicates) > 5:
            print(f"  ... and {len(duplicates) - 5} more")
    
    # Deduplicate repositories
    unique_repos = list(repo_counts.keys())
    print(f"Total lines processed: {total_lines}")
    print(f"Valid repository entries: {valid_lines}")
    print(f"Unique repositories: {len(unique_repos)}")
    
    return unique_repos


def run_hdfs_command(cmd, check=True, verbose=False):
    """Run an HDFS command via subprocess."""
    if verbose:
        print(f"Running command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=check
        )
        if verbose:
            print(f"Command completed with return code: {result.returncode}")
        return result
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {' '.join(cmd)}")
        print(f"Return code: {e.returncode}")
        print(f"Stdout: {e.stdout}")
        print(f"Stderr: {e.stderr}")
        if check:
            raise
        return None


def check_hdfs_path_exists(hdfs_path, verbose=False):
    """Check if the HDFS path exists."""
    cmd = ["hdfs", "dfs", "-test", "-e", hdfs_path]
    result = run_hdfs_command(cmd, check=False, verbose=verbose)
    exists = result.returncode == 0 if result else False
    if verbose:
        print(f"HDFS path {hdfs_path} {'exists' if exists else 'does not exist'}")
    return exists


def copy_repository(repo_path, output_dir, skip_existing=False, dry_run=False, verbose=False):
    """Copy a repository from HDFS to local directory."""
    hdfs_path = f"{HDFS_BASE_PATH}/{repo_path}"
    local_path = os.path.join(output_dir, repo_path)
    
    if verbose:
        print(f"Processing repository: {repo_path}")
        print(f"HDFS path: {hdfs_path}")
        print(f"Local path: {local_path}")
    
    # Skip if the local path already exists and skip_existing is True
    if skip_existing and os.path.exists(local_path):
        if verbose:
            print(f"Skipping existing repository: {repo_path}")
        return True
    
    # Create the local directory if it doesn't exist
    parent_dir = os.path.dirname(local_path)
    if not os.path.exists(parent_dir):
        if not dry_run:
            try:
                os.makedirs(parent_dir, exist_ok=True)
                if verbose:
                    print(f"Created directory: {parent_dir}")
            except Exception as e:
                print(f"Error creating directory {parent_dir}: {str(e)}")
                return False
        elif verbose:
            print(f"Would create directory: {parent_dir}")
    
    # Check if the HDFS path exists
    if not check_hdfs_path_exists(hdfs_path, verbose=verbose):
        print(f"Warning: HDFS path does not exist: {hdfs_path}")
        return False
    
    # Copy the repository from HDFS to local
    if dry_run:
        if verbose:
            print(f"Would copy {hdfs_path} to {parent_dir}")
        return True
    
    # First try to list the directory to catch any potential issues
    list_cmd = ["hdfs", "dfs", "-ls", hdfs_path]
    list_result = run_hdfs_command(list_cmd, check=False, verbose=verbose)
    
    if not list_result or list_result.returncode != 0:
        print(f"Warning: Could not list HDFS path: {hdfs_path}")
        print(f"Error: {list_result.stderr if list_result else 'Unknown error'}")
        return False
    
    # Proceed with the copy
    cmd = ["hdfs", "dfs", "-get", hdfs_path, parent_dir]
    result = run_hdfs_command(cmd, check=False, verbose=verbose)
    
    success = result and result.returncode == 0
    if success and verbose:
        print(f"Successfully copied {repo_path}")
    elif not success:
        stderr = result.stderr if result else "Unknown error"
        print(f"Failed to copy {repo_path}: {stderr}")
    
    return success


def process_repository(repo_path, output_dir, skip_existing, dry_run, verbose):
    """Process a single repository for parallel execution."""
    try:
        return repo_path, copy_repository(repo_path, output_dir, skip_existing, dry_run, verbose)
    except Exception as e:
        print(f"Error processing repository {repo_path}: {str(e)}")
        return repo_path, False


def main():
    """Main function."""
    args = parse_args()
    
    start_time = time.time()
    
    # Read repository paths from the JSONL files
    repositories = read_repositories(args.jsonl_files)
    
    if not repositories:
        print("No repositories found. Exiting.")
        return
    
    # Limit the number of repositories if specified
    if args.max_repos and args.max_repos < len(repositories):
        print(f"Limiting to {args.max_repos} repositories (out of {len(repositories)})")
        repositories = repositories[:args.max_repos]
    
    # Create the output directory if it doesn't exist
    if not args.dry_run:
        os.makedirs(args.output_dir, exist_ok=True)
    
    mode = "Dry run" if args.dry_run else "Copying"
    print(f"{mode} {len(repositories)} repositories to {os.path.abspath(args.output_dir)} using {args.workers} workers")
    
    # Copy repositories with progress bar
    success_count = 0
    failed_repos = []
    
    # Initialize thread-safe lock for output directory creation
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Use ProcessPoolExecutor for CPU and I/O bound operations
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
        # Submit all tasks
        future_to_repo = {
            executor.submit(
                process_repository, 
                repo_path, 
                args.output_dir, 
                args.skip_existing, 
                args.dry_run, 
                args.verbose
            ): repo_path for repo_path in repositories
        }
        
        # Process results as they complete with a progress bar
        with tqdm(total=len(repositories), desc=f"{mode} repositories") as pbar:
            for future in concurrent.futures.as_completed(future_to_repo):
                repo_path, success = future.result()
                if success:
                    success_count += 1
                else:
                    failed_repos.append(repo_path)
                pbar.update(1)
    
    elapsed_time = time.time() - start_time
    print(f"\nOperation completed in {elapsed_time:.2f} seconds")
    print(f"Successfully {'processed' if args.dry_run else 'copied'} {success_count}/{len(repositories)} repositories")
    
    if failed_repos:
        print(f"Failed to {'process' if args.dry_run else 'copy'} {len(failed_repos)} repositories:")
        for repo in failed_repos[:10]:  # Show only the first 10 failures
            print(f"  - {repo}")
        if len(failed_repos) > 10:
            print(f"  ... and {len(failed_repos) - 10} more")
        
        # Write failed repositories to a file
        failed_file = "failed_repos_dry_run.txt" if args.dry_run else "failed_repos.txt"
        with open(failed_file, "w") as f:
            for repo in failed_repos:
                f.write(f"{repo}\n")
        print(f"Failed repositories written to {failed_file}")


if __name__ == "__main__":
    main() 