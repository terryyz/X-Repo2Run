#!/usr/bin/env python3
import json
import os
import argparse
import re
from pathlib import Path
from collections import defaultdict


def extract_repo_id(repository_path):
    """Extract the repository ID from the repository path."""
    # Expected format: tmp_repo_ID/something
    match = re.search(r'tmp_repo_(\d+)', repository_path)
    if match:
        return match.group(1)
    return None


def split_jsonl(input_file, output_dir):
    """
    Split a JSONL file into multiple files based on the repository value.
    
    Args:
        input_file (str): Path to the input JSONL file
        output_dir (str): Directory to write the output files
    """
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Group JSON objects by repo ID
    repo_data = defaultdict(list)
    
    # Read the input JSONL file
    with open(input_file, 'r') as f:
        for line_num, line in enumerate(f, 1):
            try:
                data = json.loads(line.strip())
                repository = data.get('repository')
                
                if not repository:
                    print(f"Warning: Line {line_num} doesn't have a repository field. Skipping.")
                    continue
                
                repo_id = extract_repo_id(repository)
                if not repo_id:
                    print(f"Warning: Could not extract repo ID from repository path: {repository}. Skipping.")
                    continue
                
                repo_data[repo_id].append(data)
            except json.JSONDecodeError:
                print(f"Error: Could not parse JSON on line {line_num}. Skipping.")
    
    # Write each group to a separate JSONL file
    for repo_id, data_list in repo_data.items():
        output_file = os.path.join(output_dir, f"tmp_repo_{repo_id}_unittest_freq50.jsonl")
        with open(output_file, 'w') as f:
            for data in data_list:
                f.write(json.dumps(data) + '\n')
        print(f"Created {output_file} with {len(data_list)} records")


def main():
    parser = argparse.ArgumentParser(description='Split a JSONL file into multiple files based on repository values.')
    parser.add_argument('input_file', help='Path to the input JSONL file')
    parser.add_argument('-o', '--output-dir', default='output', help='Directory to write the output files')
    
    args = parser.parse_args()
    
    # Validate input file
    if not os.path.isfile(args.input_file):
        print(f"Error: Input file {args.input_file} does not exist.")
        return 1
    
    split_jsonl(args.input_file, args.output_dir)
    return 0


if __name__ == '__main__':
    exit(main()) 