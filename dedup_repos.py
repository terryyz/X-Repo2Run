#!/usr/bin/env python3

import argparse
import json
import os
import sys
import re

def dedup_jsonl(input_file, output_file, working_dir=None):
    """
    Deduplicate a JSONL file based on the "repository" key.
    Each line in the file should be a valid JSON object with a "repository" key.
    If working_dir is provided, the repository values will be updated to {working_dir}/{repository}.
    """
    seen_repos = set()
    duplicate_count = 0
    kept_count = 0
    
    # Check if input file exists
    if not os.path.isfile(input_file):
        print(f"Error: Input file '{input_file}' does not exist")
        return False
    
    try:
        with open(input_file, 'r') as infile, open(output_file, 'w') as outfile:
            for line_num, line in enumerate(infile, 1):
                line = line.strip()
                if not line:  # Skip empty lines
                    continue
                
                # Try to parse as JSON
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    # If not valid JSON, try to extract using regex
                    repo_match = re.search(r'"repository":\s*"([^"]+)"', line)
                    if repo_match:
                        repo = repo_match.group(1)
                        
                        # Update repository path if working_dir is provided
                        if working_dir:
                            new_repo = os.path.join(working_dir, repo)
                            line = line.replace(f'"repository": "{repo}"', f'"repository": "{new_repo}"')
                        
                        if repo not in seen_repos:
                            seen_repos.add(repo)
                            outfile.write(line + '\n')
                            kept_count += 1
                        else:
                            duplicate_count += 1
                    else:
                        print(f"Warning: Line {line_num} is not valid JSON and doesn't contain a repository key")
                    continue
                
                # Check if the repository key exists
                if "repository" not in data:
                    print(f"Warning: Line {line_num} doesn't have a 'repository' key")
                    continue
                
                repo = data["repository"]
                
                # Update repository path if working_dir is provided
                if working_dir:
                    data["repository"] = os.path.join(working_dir, repo)
                
                # Check if we've seen this repository before
                if repo not in seen_repos:
                    seen_repos.add(repo)
                    outfile.write(json.dumps(data) + '\n')
                    kept_count += 1
                else:
                    duplicate_count += 1
        
        print(f"Deduplication complete:")
        print(f"- Unique repositories: {len(seen_repos)}")
        print(f"- Duplicates removed: {duplicate_count}")
        print(f"- Lines in output file: {kept_count}")
        print(f"Output written to: {output_file}")
        return True
    
    except Exception as e:
        print(f"Error during deduplication: {str(e)}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Deduplicate JSONL file based on repository key")
    parser.add_argument("input_file", help="Input JSONL file path")
    parser.add_argument("-o", "--output", help="Output file path (default: input_file.dedup.jsonl)",
                        default=None)
    parser.add_argument("-w", "--working-dir", help="Working directory to prepend to repository paths",
                        default=None)
    
    args = parser.parse_args()
    
    # Set default output file if not provided
    if args.output is None:
        base_name = os.path.splitext(args.input_file)[0]
        args.output = f"{base_name}.dedup.jsonl"
    
    # Don't overwrite the input file
    if os.path.abspath(args.input_file) == os.path.abspath(args.output):
        print("Error: Output file cannot be the same as input file")
        sys.exit(1)
    
    # Run deduplication
    success = dedup_jsonl(args.input_file, args.output, args.working_dir)
    
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main() 