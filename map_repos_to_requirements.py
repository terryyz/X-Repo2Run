#!/usr/bin/env python3

import json
import argparse
import os
import re

def extract_repo_name(repo_path):
    """
    Extract the repo name from a path like "downloaded_repos/tmp_repo_31/ah-django-unchained-master"
    and normalize it by removing "-master" or "-main" suffixes.
    """
    # Extract the last part of the path
    repo_name = os.path.basename(repo_path)
    
    # Remove -master or -main suffixes
    repo_name = re.sub(r'-(master|main)$', '', repo_name)
    
    return repo_name

def find_matching_repo(repo_name, requirements_data):
    """
    Find a matching repository in the requirements data.
    Looks for repo_name in the repo_name field (ignoring organization parts)
    """
    for req_entry in requirements_data:
        # Extract the repo name portion from "org/repo" format
        full_repo_name = req_entry["repo_name"]
        if "/" in full_repo_name:
            req_repo_name = full_repo_name.split("/")[1]
        else:
            req_repo_name = full_repo_name
            
        # Check if the normalized repo names match
        if repo_name.lower() == req_repo_name.lower():
            return req_entry
    
    return None

def extract_requirements_without_version(requirements_str):
    """
    Extract just the package names without version information from a requirements string.
    Handles special cases like:
    - Index URLs (--index-url)
    - Direct URLs and git repos
    - Requirements file includes (-r)
    - Editable installs (-e)
    """
    if not requirements_str:
        return []
    
    package_names = []
    for line in requirements_str.strip().split('\n'):
        line = line.strip()
        
        # Skip empty lines and comments
        if not line or line.startswith('#'):
            continue
            
        # Skip options like --index-url
        if line.startswith('--'):
            continue
            
        # Skip requirements file includes
        if line.startswith('-r '):
            continue
            
        # Handle editable installs
        if line.startswith('-e '):
            # For git repositories, extract the egg name if present
            if '#egg=' in line:
                egg_part = line.split('#egg=')[1]
                package_name = egg_part.strip()
                if package_name:
                    package_names.append(package_name)
            continue
            
        # Skip direct URLs (http/https/git)
        if line.startswith(('http://', 'https://', 'git+', 'git://')):
            # Try to extract package name from URL if it's a model or package
            filename = line.split('/')[-1]
            if '.tar.gz' in filename or '.whl' in filename:
                # Extract package name from filename (best effort)
                package_name = re.split(r'[-=]', filename)[0].strip()
                if package_name:
                    package_names.append(package_name)
            continue
            
        # For normal package requirements, extract just the package name
        # (everything before any version specifier)
        package_name = re.split(r'[=<>~!\[]', line)[0].strip()
        if package_name:
            package_names.append(package_name)
            
    return package_names

def main():
    parser = argparse.ArgumentParser(description='Map repositories to requirements without version info')
    parser.add_argument('input_file', help='Input JSONL file with repository paths')
    parser.add_argument('requirements_file', help='Requirements JSONL file with repository requirements')
    parser.add_argument('output_file', help='Output text file for unified and deduplicated requirements')
    
    args = parser.parse_args()
    
    # Load the requirements data
    requirements_data = []
    with open(args.requirements_file, 'r') as f:
        for line in f:
            try:
                requirements_data.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                print(f"Warning: Could not parse line as JSON: {line.strip()}")
    
    # Process the input repositories
    all_requirements = set()  # Use a set to deduplicate requirements
    processed_repos = 0
    matched_repos = 0
    
    with open(args.input_file, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                if "repository" not in entry:
                    print(f"Warning: No 'repository' field found in: {line.strip()}")
                    continue
                
                processed_repos += 1
                repo_path = entry["repository"]
                repo_name = extract_repo_name(repo_path)
                
                matching_repo = find_matching_repo(repo_name, requirements_data)
                
                if matching_repo:
                    matched_repos += 1
                    req_without_version = extract_requirements_without_version(matching_repo.get("requirements", ""))
                    all_requirements.update(req_without_version)  # Add to set for deduplication
                else:
                    print(f"Warning: No matching repository found for: {repo_name} (from {repo_path})")
                    
            except json.JSONDecodeError:
                print(f"Warning: Could not parse line as JSON: {line.strip()}")
    
    # Sort and write unified and deduplicated requirements to output file
    sorted_requirements = sorted(list(all_requirements), key=str.lower)
    
    with open(args.output_file, 'w') as f:
        for req in sorted_requirements:
            f.write(f"{req}\n")
    
    print(f"Processed {processed_repos} repositories, matched {matched_repos} in requirements file.")
    print(f"Found {len(sorted_requirements)} unique requirements.")
    print(f"Results written to {args.output_file}")

if __name__ == "__main__":
    main() 