# Copyright (2025) Bytedance Ltd. and/or its affiliates 
# Licensed under the Apache License, Version 2.0

import os
import mimetypes
from pathlib import Path

# Initialize mimetypes
mimetypes.init()

# Binary and large file extensions to exclude
BINARY_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.ico', '.svg',
    '.mp3', '.mp4', '.wav', '.avi', '.mov', '.mkv', '.flv',
    '.zip', '.tar', '.gz', '.rar', '.7z', '.jar', '.war',
    '.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx',
    '.bin', '.exe', '.dll', '.so', '.dylib', '.class'
}

# Files/directories to exclude from listings
EXCLUDED_ITEMS = {
    '__pycache__', '.git', '.idea', '.vscode', 'node_modules',
    '.DS_Store', '.pytest_cache', '.coverage', 'venv', 'env',
    '__pypackages__', '.env', '.venv', '.eggs'
}

def is_binary_file(file_path):
    """Check if a file is binary."""
    # Check extension first for efficiency
    ext = os.path.splitext(file_path)[1].lower()
    if ext in BINARY_EXTENSIONS:
        return True
    
    # Check mimetype
    mime_type = mimetypes.guess_type(file_path)[0]
    if mime_type and not mime_type.startswith(('text/', 'application/json', 'application/xml')):
        return True
    
    # Fall back to reading a bit of the file
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(1024)
            return b'\0' in chunk  # Null bytes suggest binary content
    except (IOError, IsADirectoryError):
        return False

def get_repo_structure(repo_path, max_depth=5, max_files_per_dir=30):
    """
    Generate a directory tree of the repository with smart filtering.
    
    Args:
        repo_path: Path to the repository
        max_depth: Maximum depth to display
        max_files_per_dir: Maximum number of files to display per directory
        
    Returns:
        str: Formatted directory tree
    """
    if not os.path.exists(repo_path):
        return f"Repository path '{repo_path}' does not exist"
    
    result = []
    
    def _generate_tree(path, prefix="", is_last=True, current_depth=0):
        if current_depth > max_depth:
            result.append(f"{prefix}├── ... (max depth reached)")
            return
            
        if not os.path.isdir(path):
            return
            
        try:
            all_files = os.listdir(path)
        except PermissionError:
            result.append(f"{prefix}├── ... (permission denied)")
            return
            
        # Filter out excluded files and sort
        files = sorted([f for f in all_files if not any(ex in f for ex in EXCLUDED_ITEMS)])
        
        # First list important files, then directories, then regular files
        important_files = [f for f in files if not os.path.isdir(os.path.join(path, f)) and 
                        (f.lower().startswith('readme') or f == 'requirements.txt' or
                         f == 'package.json' or f == 'dockerfile' or f == 'makefile')]
        
        dirs = [f for f in files if os.path.isdir(os.path.join(path, f))]
        regular_files = [f for f in files if not os.path.isdir(os.path.join(path, f)) and f not in important_files]
        
        # Sort each category
        important_files.sort()
        dirs.sort()
        regular_files.sort()
        
        # Combine with important files first
        organized_files = important_files + dirs + regular_files
        
        # Handle large directories
        if len(organized_files) > max_files_per_dir:
            shown_files = organized_files[:max_files_per_dir]
            skipped = len(organized_files) - max_files_per_dir
            organized_files = shown_files
            organized_files.append(f"... ({skipped} more items)")
        
        for i, file in enumerate(organized_files):
            is_last_file = i == len(organized_files) - 1
            file_path = os.path.join(path, file)
            
            # Format the current item
            if is_last_file:
                result.append(f"{prefix}└── {file}")
                new_prefix = prefix + "    "
            else:
                result.append(f"{prefix}├── {file}")
                new_prefix = prefix + "│   "
            
            # Recurse if directory
            if os.path.isdir(file_path) and "more items" not in file:
                _generate_tree(file_path, new_prefix, is_last_file, current_depth + 1)
    
    _generate_tree(repo_path)
    return '\n'.join(result)

def find_main_readme(repo_path):
    """
    Find the main README file in the repository.
    
    Args:
        repo_path: Path to the repository
        
    Returns:
        dict: Information about the main README
    """
    readme_patterns = ['README.md', 'Readme.md', 'readme.md', 'README.rst', 'README.txt', 'README']
    
    for pattern in readme_patterns:
        readme_path = os.path.join(repo_path, pattern)
        if os.path.exists(readme_path):
            try:
                with open(readme_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    return {
                        'path': pattern,
                        'content': content
                    }
            except UnicodeDecodeError:
                try:
                    # Try with latin-1 encoding
                    with open(readme_path, 'r', encoding='latin-1') as f:
                        content = f.read()
                        return {
                            'path': pattern,
                            'content': content
                        }
                except Exception:
                    pass
            except Exception:
                pass
    
    return {
        'path': None,
        'content': "No README file found at the repository root."
    }

if __name__ == "__main__":
    repo_path = "./"
    
    print("=== Testing repo structure printer ===")
    print(get_repo_structure(repo_path, max_depth=3, max_files_per_dir=5))  # Test the repo structure printer
    print("\n=== Testing main README finder ===")
    found_readme = find_main_readme(repo_path)
    for path, content in found_readme.items():
        print(f"README path: {path}")
        print(f"README content: {content[:100]}...")
        print()
    