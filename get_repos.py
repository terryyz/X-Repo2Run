#!/usr/bin/env python3

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

def extract_repositories(input_file):
    """Extract repository paths from the input file."""
    repos = []
    
    # Check if file exists
    if not os.path.isfile(input_file):
        print(f"Error: File '{input_file}' does not exist")
        sys.exit(1)
    
    # Read the file line by line to handle large files
    with open(input_file, 'r') as f:
        for line in f:
            # Look for "repository": "path" pattern
            match = re.search(r'"repository":\s*"([^"]+)"', line)
            if match:
                repo_path = match.group(1)
                # Clean up path if needed (ensure it's just tmp_repo_XX/name format)
                if "/" in repo_path:
                    parts = repo_path.split("/")
                    for i, part in enumerate(parts):
                        if part.startswith("tmp_repo_"):
                            repo_path = "/".join(parts[i:])
                            break
                repos.append(repo_path)
    
    return repos

def copy_from_hdfs(repo_path, hdfs_base_path, local_dir):
    """Copy a repository from HDFS to local directory."""
    full_hdfs_path = f"{hdfs_base_path}/{repo_path}"
    
    # Extract repo name and directory
    repo_name = os.path.basename(repo_path)
    parent_dir = os.path.basename(os.path.dirname(full_hdfs_path))
    
    # Create local directory
    local_repo_dir = os.path.join(local_dir, parent_dir)
    os.makedirs(local_repo_dir, exist_ok=True)
    
    # Execute HDFS copy command
    print(f"Copying {full_hdfs_path} to {local_repo_dir}/")
    
    try:
        result = subprocess.run(
            ["hdfs", "dfs", "-copyToLocal", full_hdfs_path, local_repo_dir],
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode == 0:
            print(f"Successfully copied {repo_name}")
            return True, None
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            print(f"Failed to copy {repo_name} - {error_msg}")
            return False, full_hdfs_path
    except Exception as e:
        print(f"Error copying {repo_name}: {str(e)}")
        return False, full_hdfs_path

def main():
    parser = argparse.ArgumentParser(description="Copy repositories from HDFS to local directory")
    parser.add_argument("input_file", help="Input file containing repository paths")
    parser.add_argument("--output-dir", "-o", default="./downloaded_repos", 
                        help="Local directory to store repositories (default: ./downloaded_repos)")
    args = parser.parse_args()
    
    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)
    
    # HDFS base path
    hdfs_base_path = "hdfs://harunava/home/byte_data_seed_azureb_tteng/user/codeai/unzip_code_repo_batch"
    
    # Failed repositories list
    failed_file = os.path.join(args.output_dir, "failed_repos.txt")
    
    # Extract repositories
    print(f"Extracting repository paths from {args.input_file}...")
    repositories = extract_repositories(args.input_file)
    
    print(f"Found {len(repositories)} repositories to download.")
    
    # Track success and failure
    success_count = 0
    failed_count = 0
    failed_repos = []
    
    # Process each repository
    print(f"Copying repositories from HDFS to local directory: {args.output_dir}")
    for repo_path in repositories:
        success, failed_path = copy_from_hdfs(repo_path, hdfs_base_path, args.output_dir)
        if success:
            success_count += 1
        else:
            failed_count += 1
            if failed_path:
                failed_repos.append(failed_path)
    
    # Save failed repositories to file
    if failed_repos:
        with open(failed_file, 'w') as f:
            for repo in failed_repos:
                f.write(f"{repo}\n")
    
    # Summary
    print("\n===== Download Summary =====")
    print(f"Total repositories: {len(repositories)}")
    print(f"Successfully copied: {success_count}")
    print(f"Failed to copy: {failed_count}")
    if failed_count > 0:
        print(f"Failed repositories are listed in: {failed_file}")
    print(f"Done copying repositories to {args.output_dir}")
    
    # Retry command suggestion
    if failed_count > 0:
        print("\nTo retry downloading failed repositories with elevated permissions, try:")
        print(f"cat {failed_file} | while read repo; do echo \"Processing $repo\"; " 
              f"hdfs dfs -copyToLocal \"$repo\" \"{args.output_dir}/$(basename \"$(dirname \"$repo\")\")/\"; done")

if __name__ == "__main__":
    main() 