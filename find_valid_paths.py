#!/usr/bin/env python3

import os
import argparse
import glob
from pathlib import Path


def find_single_folder_paths(base_paths, output_file, target_depth=1):
    """
    Find paths that contain only a single folder and write their full paths to a file.
    
    Args:
        base_paths (list): List of base directory paths to check
        output_file (str): Path to the output text file
        target_depth (int): Target depth to find single folder paths (default: 1)
    """
    valid_paths = []
    output_file = Path(output_file).resolve()
    
    for base_path in base_paths:
        base_path = Path(base_path).resolve()
        print(f"Processing directory: {base_path}")
        # Start at depth 0 (the base path itself)
        process_directory(base_path, valid_paths, depth=0, target_depth=target_depth)
    
    # Write valid paths to output file
    with open(output_file, 'w') as f:
        for path in valid_paths:
            f.write(f"{path}\n")
    
    print(f"Found {len(valid_paths)} paths with single folders at depth {target_depth}. Results written to {output_file}")
    
    # If no valid paths were found, print a message
    if not valid_paths:
        print(f"No paths with single folders found at depth {target_depth}.")
    
    return valid_paths


def should_ignore_folder(path):
    """
    Check if a folder should be ignored (hidden or system folder).
    
    Args:
        path (Path): Path to check
        
    Returns:
        bool: True if the folder should be ignored, False otherwise
    """
    # Ignore folders starting with a dot (hidden)
    if path.name.startswith('.'):
        return True
    
    # Ignore folders starting with double underscores (like __pycache__)
    if path.name.startswith('__'):
        return True
    
    return False


def process_directory(dir_path, valid_paths, depth=0, target_depth=1):
    """
    Process a directory to find paths with single folders at the target depth.
    
    Args:
        dir_path (Path): Directory path to process
        valid_paths (list): List to store valid paths
        depth (int): Current recursion depth
        target_depth (int): Target depth to find single folder paths
    """
    # If we've exceeded target depth, don't process further
    if depth > target_depth:
        return
        
    try:
        # Get all items in the directory
        items = list(dir_path.iterdir())
        
        # Filter only directories that should not be ignored
        dir_items = [item for item in items if item.is_dir() and not should_ignore_folder(item)]
        
        # If this directory contains only one subdirectory
        if len(dir_items) == 1:
            # Only add to valid paths if we're at exactly the target depth
            if depth == target_depth:
                absolute_path = str(dir_items[0])
                valid_paths.append(absolute_path)
                print(f"Found single folder path: {absolute_path}")
            
            # Recursively check the single subdirectory
            process_directory(dir_items[0], valid_paths, depth + 1, target_depth)
        else:
            # Recursively process all subdirectories
            for subdir in dir_items:
                process_directory(subdir, valid_paths, depth + 1, target_depth)
    
    except (PermissionError, OSError) as e:
        print(f"Warning: Could not access directory {dir_path}: {e}")


def expand_wildcard_path(path_pattern):
    """
    Expand a wildcard path pattern into a list of actual paths.
    
    Args:
        path_pattern (str): Path pattern that may contain wildcards
    
    Returns:
        list: List of expanded paths
    """
    expanded_paths = glob.glob(path_pattern)
    if not expanded_paths:
        print(f"Warning: Path pattern '{path_pattern}' did not match any directories")
    
    # Filter out paths that aren't directories and should be ignored
    valid_paths = []
    for p in expanded_paths:
        path = Path(p)
        if path.is_dir() and not should_ignore_folder(path):
            valid_paths.append(p)
    
    return valid_paths


def main():
    parser = argparse.ArgumentParser(description="Find paths that contain only a single folder")
    parser.add_argument("base_path", help="Base path to check for single folder paths (supports wildcards)")
    parser.add_argument("--output", "-o", default="single_folder_paths.txt", 
                        help="Output file path (default: single_folder_paths.txt)")
    parser.add_argument("--depth", "-d", type=int, default=1,
                        help="Target depth to find single folder paths (default: 1)")
    
    args = parser.parse_args()
    
    # Expand the wildcard path pattern
    expanded_paths = expand_wildcard_path(args.base_path)
    
    if not expanded_paths:
        print(f"Error: Path pattern '{args.base_path}' did not match any existing directories")
        return
    
    find_single_folder_paths(expanded_paths, args.output, args.depth)


if __name__ == "__main__":
    main()