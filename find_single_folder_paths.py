#!/usr/bin/env python3

import os
import argparse
from pathlib import Path


def find_single_folder_paths(base_path, output_file):
    """
    Find paths that contain only a single folder and write their full paths to a file.
    
    Args:
        base_path (str): Base directory path to check
        output_file (str): Path to the output text file
    """
    valid_paths = []
    base_path = Path(base_path).resolve()
    output_file = Path(output_file).resolve()
    
    print(f"Processing directory: {base_path}")
    
    def process_directory(dir_path, depth=0):
        try:
            # Get all items in the directory
            items = list(dir_path.iterdir())
            
            # Filter only directories
            dir_items = [item for item in items if item.is_dir()]
            
            # If this directory contains only one subdirectory and we're not too deep
            if len(dir_items) == 1 and depth < 2:
                # Construct the absolute path
                absolute_path = str(dir_items[0])
                
                valid_paths.append(absolute_path)
                print(f"Found single folder path: {absolute_path}")
                
                # Recursively check the single subdirectory if not too deep
                if depth < 1:
                    process_directory(dir_items[0], depth + 1)
            
            # Recursively process all subdirectories if not too deep
            if depth < 1:
                for subdir in dir_items:
                    process_directory(subdir, depth + 1)
        
        except (PermissionError, OSError) as e:
            print(f"Warning: Could not access directory {dir_path}: {e}")
    
    # Start processing from the base path
    process_directory(base_path)
    
    # Write valid paths to output file
    with open(output_file, 'w') as f:
        for path in valid_paths:
            f.write(f"{path}\n")
    
    print(f"Found {len(valid_paths)} paths with single folders. Results written to {output_file}")
    
    # If no valid paths were found, print a message
    if not valid_paths:
        print("No paths with single folders found.")
    
    return valid_paths


def main():
    parser = argparse.ArgumentParser(description="Find paths that contain only a single folder")
    parser.add_argument("base_path", help="Base path to check for single folder paths")
    parser.add_argument("--output", "-o", default="single_folder_paths.txt", 
                        help="Output file path (default: single_folder_paths.txt)")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.base_path):
        print(f"Error: Base path {args.base_path} does not exist")
        return
    
    find_single_folder_paths(args.base_path, args.output)


if __name__ == "__main__":
    main()