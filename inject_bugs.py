import json
import argparse
import os
import shutil
import sys
from pathlib import Path
from tqdm import tqdm
import concurrent.futures
import threading

# Lock for thread-safe file writing
file_lock = threading.Lock()

def inject_bug(base_repo, test_idx, bug_idx, bug, data, output_jsonl):
    """
    Process a single bug injection in a worker process
    """
    # Create the new repository name with proper path handling
    bug_type = bug.get("bug_type", "unknown")
    base_dir = os.path.dirname(base_repo)
    base_name = os.path.basename(base_repo)
    new_repo_name = os.path.join(base_dir, f"{base_name}-tests-{test_idx}-bugs-{bug_idx}-type-{bug_type}")
    
    # Copy the entire repository
    if os.path.exists(new_repo_name):
        shutil.rmtree(new_repo_name)
    shutil.copytree(base_repo, new_repo_name)
    
    # Get the file to modify and the code changes
    file_path = bug.get("file_path")
    original_code = bug.get("original_code")
    buggy_code = bug.get("buggy_code")
    
    error_message = None
    if file_path and original_code and buggy_code:
        full_file_path = os.path.join(new_repo_name, file_path)
        
        # Ensure directory exists (in case file_path contains directories)
        os.makedirs(os.path.dirname(full_file_path), exist_ok=True)
        
        # Read the file content
        try:
            # Check if the file exists
            if not os.path.exists(full_file_path):
                error_message = f"Error: File not found: {full_file_path}"
            else:
                with open(full_file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Replace the original code with buggy code
                new_content = content.replace(original_code, buggy_code)
                
                # Write back the modified content
                with open(full_file_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
        except Exception as e:
            error_message = f"Error processing file {full_file_path}: {e}"
    
    # Create a copy of the data with updated repository path
    output_data = data.copy()
    output_data["repository"] = new_repo_name
    
    # Remove "content", "response", and "bug" fields from each test instance in the "tests" array
    if "tests" in output_data and isinstance(output_data["tests"], list):
        for test in output_data["tests"]:
            if "content" in test:
                del test["content"]
            if "response" in test:
                del test["response"]
            if "bug" in test:
                del test["bug"]
    
    # Write to the output JSONL file (thread-safe)
    with file_lock:
        with open(output_jsonl, 'a') as out_file:
            out_file.write(json.dumps(output_data) + "\n")
    
    return error_message, new_repo_name

def process_repository(input_file, output_jsonl, workers=None, quiet=False):
    """
    Process the input file, copy repositories with bugs injected, and write to output JSONL.
    """
    # Remove existing output file if it exists
    if os.path.exists(output_jsonl):
        os.remove(output_jsonl)
        if not quiet:
            print(f"Removed existing output file: {output_jsonl}")
    
    # Determine the appropriate number of workers
    if workers is None:
        max_workers = max(os.cpu_count()-5, 1)  # Limit to 8 workers to avoid excessive disk I/O
    else:
        max_workers = workers
    
    # Read all lines from the input file first
    try:
        with open(input_file, 'r') as f:
            lines = [line.strip() for line in f if line.strip()]
    except Exception as e:
        if not quiet:
            print(f"Error reading input file: {e}")
        return
    
    # Process each line as a separate JSON object
    for line_idx, line in enumerate(tqdm(lines, desc="Processing repositories")):
        try:
            data = json.loads(line)
        except json.JSONDecodeError as e:
            if not quiet:
                tqdm.write(f"Error parsing line {line_idx+1} as JSON: {e}")
            continue
            
        # Get the base repository path
        base_repo = data.get("repository")
        if not base_repo:
            if not quiet:
                tqdm.write(f"Repository path not specified in line {line_idx+1}")
            continue
            
        if not os.path.exists(base_repo):
            if not quiet:
                tqdm.write(f"Repository {base_repo} not found")
            continue
        
        # First, add the original repository to the output
        with open(output_jsonl, 'a') as out_file:
            out_file.write(json.dumps(data) + "\n")
        
        # Collect all bugs across all tests for this repository
        bugs_list = []
        for test_idx, test in enumerate(data.get("tests", [])):
            bugs = test.get("bug", [])
            if not bugs:
                # Try alternative key 'bugs' if 'bug' is not found
                bugs = test.get("bugs", [])
            
            for bug_idx, bug in enumerate(bugs):
                bugs_list.append((test_idx, bug_idx, bug))
        
        # No bugs to process
        if not bugs_list:
            if not quiet:
                tqdm.write(f"No bugs found for repository {base_repo}")
            continue
            
        # Process bugs in parallel
        with tqdm(total=len(bugs_list), desc=f"Injecting bugs for {os.path.basename(base_repo)}", leave=False) as pbar:
            # Sequential processing for debugging if needed
            if max_workers == 1:
                for test_idx, bug_idx, bug in bugs_list:
                    error_message, repo_name = inject_bug(base_repo, test_idx, bug_idx, bug, data, output_jsonl)
                    if error_message and not quiet:
                        tqdm.write(error_message)
                    if not quiet:
                        tqdm.write(f"Created repository: {repo_name}")
                    pbar.update(1)
            else:
                # Use ProcessPoolExecutor for parallel processing
                with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
                    # Submit all bug injection tasks
                    futures = {
                        executor.submit(
                            inject_bug, base_repo, test_idx, bug_idx, bug, data, output_jsonl
                        ): (test_idx, bug_idx) 
                        for test_idx, bug_idx, bug in bugs_list
                    }
                    
                    # Process results as they complete
                    for future in concurrent.futures.as_completed(futures):
                        error_message, repo_name = future.result()
                        if error_message and not quiet:
                            tqdm.write(error_message)
                        if not quiet:
                            tqdm.write(f"Created repository: {repo_name}")
                        pbar.update(1)

def main():
    parser = argparse.ArgumentParser(description="Copy repositories and inject bugs for each test")
    parser.add_argument("input_file", help="Input JSONL file with tests and bugs")
    parser.add_argument("-o", "--output", required=True, help="Output JSONL file to append to")
    parser.add_argument("-w", "--workers", type=int, default=None, 
                      help="Maximum number of worker processes (default: number of CPU cores, max 8)")
    parser.add_argument("--debug", action="store_true", help="Run in sequential mode for debugging")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress error messages and logs")
    
    args = parser.parse_args()
    
    # Use sequential processing if debug mode is enabled
    workers = 1 if args.debug else args.workers
    
    process_repository(args.input_file, args.output, workers, args.quiet)

if __name__ == "__main__":
    main()