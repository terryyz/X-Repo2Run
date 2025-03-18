#!/usr/bin/env python3

import json
import os
import argparse


def extract_valid_subpaths(jsonl_file, base_path, output_file):
    """
    Read a JSONL file, extract repo_names and check if they exist as subpaths in base_path.
    Write valid subpaths to the output file.
    
    Args:
        jsonl_file (str): Path to the input JSONL file
        base_path (str): Base directory path to check for subpaths
        output_file (str): Path to the output text file
    """
    valid_subpaths = []
    
    # Read JSONL file
    with open(jsonl_file, 'r') as f:
        for line in f:
            if not line.strip():
                continue
                
            try:
                data = json.loads(line.strip())
                repo_name = data.get('repo_name')
                
                if not repo_name:
                    continue
                
                # Split the repo name to get owner and repository
                parts = repo_name.split('/')
                if len(parts) != 2:
                    continue
                
                owner, repo = parts
                potential_path = os.path.join(base_path, owner, repo)
                
                # Check if the path exists within base_path (case-insensitive search)
                if os.path.exists(potential_path):
                    valid_subpaths.append(os.path.join(owner, repo))
                else:
                    # Try a case-insensitive search
                    for root, dirs, files in os.walk(base_path):
                        for dir_name in dirs:
                            if dir_name.lower() == owner.lower():
                                owner_path = os.path.join(root, dir_name)
                                for subdir in os.listdir(owner_path):
                                    if subdir.lower() == repo.lower():
                                        valid_subpaths.append(os.path.join(dir_name, subdir))
                                        break
            except json.JSONDecodeError:
                print(f"Warning: Could not parse line as JSON: {line}")
    
    # Write valid subpaths to output file
    with open(output_file, 'w') as f:
        for subpath in valid_subpaths:
            f.write(f"{subpath}\n")
    
    print(f"Found {len(valid_subpaths)} valid subpaths. Written to {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Find valid repository subpaths from a JSONL file")
    parser.add_argument("jsonl_file", help="Path to the input JSONL file")
    parser.add_argument("base_path", help="Base path to check for repository subpaths")
    parser.add_argument("--output", "-o", default="valid_subpaths.txt", 
                        help="Output file path (default: valid_subpaths.txt)")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.jsonl_file):
        print(f"Error: Input file {args.jsonl_file} does not exist")
        return
    
    if not os.path.exists(args.base_path):
        print(f"Error: Base path {args.base_path} does not exist")
        return
    
    extract_valid_subpaths(args.jsonl_file, args.base_path, args.output)


if __name__ == "__main__":
    main() 