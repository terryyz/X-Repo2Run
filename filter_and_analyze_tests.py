#!/usr/bin/env python3
"""
Script to filter JSONL files processed by add_test_groups.py, removing instances where
a tested file has only one module with less than 6 test cases mapped to it.
Also calculates and displays overall statistics.

Supports processing multiple input files with corresponding output files.
Uses parallel processing for improved performance.
"""

import json
import sys
import os
import glob
import argparse
import multiprocessing
from collections import defaultdict
from tqdm import tqdm
from functools import partial

def filter_and_analyze_jsonl(input_file, output_file, append_mode=False):
    """
    Filter and analyze a JSONL file that has been processed by add_test_groups.py
    
    Parameters:
    - input_file: Path to the input file
    - output_file: Path to the output file
    - append_mode: If True, append to output file instead of overwriting
    """
    # Make sure the output directory exists
    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Remove output file if it exists and we're not in append mode
    if not append_mode and os.path.exists(output_file):
        os.remove(output_file)
    
    # Statistics tracking
    total_repos = 0
    repo_files = defaultdict(int)       # Files per repository
    all_modules_count = []              # Number of modules per file
    all_tests_per_module = []           # Number of tests per module
    modules_with_few_tests = 0          # Modules with < 6 tests
    total_modules = 0                   # Total modules
    
    # New statistics
    files_without_modules = 0           # Files with no specific modules identified
    total_files_with_groups = 0         # Total files with groups
    
    # Module type statistics
    class_methods_count = 0             # Number of class methods
    functions_count = 0                 # Number of standalone functions
    classes_count = 0                   # Number of classes
    
    # Count total lines for progress bar
    try:
        total_lines = sum(1 for _ in open(input_file, 'r', encoding='utf-8', errors='replace'))
    except Exception as e:
        print(f"Error counting lines in {input_file}: {e}")
        return None
    
    # Process the input file
    with tqdm(total=total_lines, desc=f"Processing {input_file}", unit="lines") as pbar:
        try:
            with open(input_file, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        repository = data.get("repository", "unknown")
                        
                        # Count repositories (only once)
                        if repository not in repo_files:
                            total_repos += 1
                        
                        # Process each test in the "tests" section
                        if "tests" in data:
                            should_keep = True
                            
                            # Handle dictionary-style tests
                            if isinstance(data["tests"], dict):
                                # Filter tests and collect statistics
                                tests_to_remove = []
                                for test_key, test_info in data["tests"].items():
                                    if "group" in test_info:
                                        group = test_info["group"]
                                        total_files_with_groups += 1
                                        
                                        # Check if this is a file without specific modules
                                        file_basename = os.path.basename(test_key)
                                        is_file_only_group = len(group) == 1 and file_basename in group
                                        
                                        if is_file_only_group:
                                            files_without_modules += 1
                                            # Skip including in other statistics
                                            continue
                                        
                                        # Count modules in this file
                                        modules_in_file = len(group)
                                        all_modules_count.append(modules_in_file)
                                        total_modules += modules_in_file
                                        
                                        # Check each module and classify type
                                        for module, test_cases in group.items():
                                            # Count test cases per module
                                            test_count = len(test_cases)
                                            all_tests_per_module.append(test_count)
                                            
                                            # Track modules with few tests
                                            if test_count < 6:
                                                modules_with_few_tests += 1
                                            
                                            # Determine module type (class method, function, or class)
                                            if '.' in module:
                                                class_methods_count += 1
                                            else:
                                                # Check if likely a class (first letter uppercase)
                                                if module and module[0].isupper():
                                                    classes_count += 1
                                                else:
                                                    functions_count += 1
                                        
                                        # Filter criteria: one module with less than 6 test cases
                                        if modules_in_file == 1 and len(next(iter(group.values()))) < 6:
                                            tests_to_remove.append(test_key)
                                
                                # Remove filtered tests
                                for key in tests_to_remove:
                                    del data["tests"][key]
                                
                                # Count files after filtering for repo statistics
                                repo_files[repository] = len(data["tests"])
                                
                                # Don't keep if all tests were removed
                                if not data["tests"]:
                                    should_keep = False
                            
                            # Handle list-style tests
                            elif isinstance(data["tests"], list):
                                # Filter tests and collect statistics
                                filtered_tests = []
                                for test_info in data["tests"]:
                                    if isinstance(test_info, dict) and "group" in test_info:
                                        group = test_info["group"]
                                        total_files_with_groups += 1
                                        
                                        # Try to get the file path to check for file-only grouping
                                        file_path = test_info.get("file", test_info.get("path", ""))
                                        file_basename = os.path.basename(file_path)
                                        
                                        # Check if this is a file without specific modules
                                        is_file_only_group = len(group) == 1 and file_basename in group
                                        
                                        if is_file_only_group:
                                            files_without_modules += 1
                                            # Skip including in other statistics
                                            filtered_tests.append(test_info)  # Still keep this entry in output
                                            continue
                                        
                                        # Count modules in this file
                                        modules_in_file = len(group)
                                        all_modules_count.append(modules_in_file)
                                        total_modules += modules_in_file
                                        
                                        # Check each module and classify type
                                        for module, test_cases in group.items():
                                            # Count test cases per module
                                            test_count = len(test_cases)
                                            all_tests_per_module.append(test_count)
                                            
                                            # Track modules with few tests
                                            if test_count < 6:
                                                modules_with_few_tests += 1
                                            
                                            # Determine module type (class method, function, or class)
                                            if '.' in module:
                                                class_methods_count += 1
                                            else:
                                                # Check if likely a class (first letter uppercase)
                                                if module and module[0].isupper():
                                                    classes_count += 1
                                                else:
                                                    functions_count += 1
                                        
                                        # Filter criteria: one module with less than 6 test cases
                                        if not (modules_in_file == 1 and len(next(iter(group.values()))) < 6):
                                            filtered_tests.append(test_info)
                                
                                # Update with filtered tests
                                data["tests"] = filtered_tests
                                
                                # Count files after filtering for repo statistics
                                repo_files[repository] = len(data["tests"])
                                
                                # Don't keep if all tests were removed
                                if not data["tests"]:
                                    should_keep = False
                            
                            # Write filtered data if it should be kept
                            if should_keep:
                                write_mode = 'a' if os.path.exists(output_file) or append_mode else 'w'
                                with open(output_file, write_mode, encoding='utf-8') as out_f:
                                    out_f.write(json.dumps(data) + '\n')
                    
                    except Exception as e:
                        print(f"Error processing line: {e}")
                    
                    # Update progress bar
                    pbar.update(1)
        except Exception as e:
            print(f"Error opening file {input_file}: {e}")
            return None
    
    # Calculate statistics
    avg_modules_per_file = sum(all_modules_count) / len(all_modules_count) if all_modules_count else 0
    avg_files_per_repo = sum(repo_files.values()) / total_repos if total_repos else 0
    avg_tests_per_module = sum(all_tests_per_module) / len(all_tests_per_module) if all_tests_per_module else 0
    percent_modules_with_few_tests = (modules_with_few_tests / total_modules * 100) if total_modules else 0
    percent_files_without_modules = (files_without_modules / total_files_with_groups * 100) if total_files_with_groups else 0
    
    # Calculate module type percentages
    percent_class_methods = (class_methods_count / total_modules * 100) if total_modules else 0
    percent_functions = (functions_count / total_modules * 100) if total_modules else 0
    percent_classes = (classes_count / total_modules * 100) if total_modules else 0
    
    # Return statistics
    return {
        "total_repos": total_repos,
        "total_modules": total_modules,
        "all_modules_count": all_modules_count, 
        "all_tests_per_module": all_tests_per_module,
        "avg_modules_per_file": avg_modules_per_file,
        "avg_files_per_repo": avg_files_per_repo,
        "avg_tests_per_module": avg_tests_per_module,
        "modules_with_few_tests": modules_with_few_tests,
        "percent_modules_with_few_tests": percent_modules_with_few_tests,
        "files_without_modules": files_without_modules,
        "total_files_with_groups": total_files_with_groups,
        "percent_files_without_modules": percent_files_without_modules,
        "class_methods_count": class_methods_count,
        "functions_count": functions_count,
        "classes_count": classes_count,
        "percent_class_methods": percent_class_methods,
        "percent_functions": percent_functions,
        "percent_classes": percent_classes
    }

def process_file_pair(file_pair, single_output_mode=False, file_index=0, total_files=1):
    """Process a single input-output file pair and return statistics"""
    input_file, output_file = file_pair
    is_appending = (file_index > 0) and single_output_mode
    
    if is_appending:
        print(f"Processing {input_file} -> appending to {output_file} (process {multiprocessing.current_process().name})")
    else:
        print(f"Processing {input_file} -> {output_file} (process {multiprocessing.current_process().name})")
    
    try:
        stats = filter_and_analyze_jsonl(input_file, output_file, append_mode=is_appending)
        if stats:
            print(f"Completed processing {input_file}")
            return stats
    except Exception as e:
        print(f"Error processing {input_file}: {e}")
    
    return None

def aggregate_statistics(stats_list):
    """Aggregate statistics from multiple file processing runs"""
    # Initialize aggregated stats
    agg_stats = {
        "total_repos": 0,
        "total_modules": 0,
        "all_modules_count": [],
        "all_tests_per_module": [],
        "modules_with_few_tests": 0,
        "files_without_modules": 0,
        "total_files_with_groups": 0,
        "class_methods_count": 0,
        "functions_count": 0,
        "classes_count": 0
    }
    
    # Combine repositories (assuming potential overlap)
    repos_set = set()
    
    # Aggregate statistics
    for stats in stats_list:
        if stats is None:
            continue
            
        # Add to repositories set (will handle duplicates)
        repos_set.add(stats["total_repos"])
        
        # Add counts
        agg_stats["total_modules"] += stats["total_modules"]
        agg_stats["all_modules_count"].extend(stats["all_modules_count"])
        agg_stats["all_tests_per_module"].extend(stats["all_tests_per_module"])
        agg_stats["modules_with_few_tests"] += stats["modules_with_few_tests"]
        agg_stats["files_without_modules"] += stats["files_without_modules"]
        agg_stats["total_files_with_groups"] += stats["total_files_with_groups"]
        agg_stats["class_methods_count"] += stats["class_methods_count"]
        agg_stats["functions_count"] += stats["functions_count"]
        agg_stats["classes_count"] += stats["classes_count"]
    
    # Set total repositories
    agg_stats["total_repos"] = len(repos_set)
    
    # Calculate aggregated averages and percentages
    agg_stats["avg_modules_per_file"] = sum(agg_stats["all_modules_count"]) / len(agg_stats["all_modules_count"]) if agg_stats["all_modules_count"] else 0
    agg_stats["avg_tests_per_module"] = sum(agg_stats["all_tests_per_module"]) / len(agg_stats["all_tests_per_module"]) if agg_stats["all_tests_per_module"] else 0
    
    # We don't have a good way to calculate avg_files_per_repo across multiple files
    agg_stats["avg_files_per_repo"] = 0  # This would need to be tracked differently
    
    # Calculate percentages
    agg_stats["percent_modules_with_few_tests"] = (agg_stats["modules_with_few_tests"] / agg_stats["total_modules"] * 100) if agg_stats["total_modules"] else 0
    agg_stats["percent_files_without_modules"] = (agg_stats["files_without_modules"] / agg_stats["total_files_with_groups"] * 100) if agg_stats["total_files_with_groups"] else 0
    agg_stats["percent_class_methods"] = (agg_stats["class_methods_count"] / agg_stats["total_modules"] * 100) if agg_stats["total_modules"] else 0
    agg_stats["percent_functions"] = (agg_stats["functions_count"] / agg_stats["total_modules"] * 100) if agg_stats["total_modules"] else 0
    agg_stats["percent_classes"] = (agg_stats["classes_count"] / agg_stats["total_modules"] * 100) if agg_stats["total_modules"] else 0
    
    return agg_stats

def print_statistics(stats):
    """Print statistics in a readable format"""
    print("\n===== Statistics =====")
    print(f"Total repositories: {stats['total_repos']}")
    print(f"Total files with groups: {stats['total_files_with_groups']}")
    print(f"Files without specific modules: {stats['files_without_modules']} ({stats['percent_files_without_modules']:.2f}%)")
    print(f"Average tested modules per file: {stats['avg_modules_per_file']:.2f}")
    if stats['avg_files_per_repo'] > 0:  # Only show if available
        print(f"Average tested files per repository: {stats['avg_files_per_repo']:.2f}")
    print(f"Average test cases per module: {stats['avg_tests_per_module']:.2f}")
    print(f"Percentage of modules with less than 6 test cases: {stats['percent_modules_with_few_tests']:.2f}%")
    
    print("\n=== Module Type Breakdown ===")
    print(f"Class methods: {stats['class_methods_count']} ({stats['percent_class_methods']:.2f}%)")
    print(f"Standalone functions: {stats['functions_count']} ({stats['percent_functions']:.2f}%)")
    print(f"Classes: {stats['classes_count']} ({stats['percent_classes']:.2f}%)")

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='Filter and analyze JSONL files processed by add_test_groups.py')
    
    # Group for input specification
    input_group = parser.add_mutually_exclusive_group(required=True)
    
    # Option 1: Single input/output pair
    input_group.add_argument('-s', '--single', nargs=2, metavar=('INPUT_FILE', 'OUTPUT_FILE'),
                           help='Process a single input file and write to output file')
    
    # Option 2: Multiple input files with individual output mappings
    input_group.add_argument('-m', '--multiple', nargs='+', metavar='INPUT:OUTPUT',
                           help='Process multiple input:output file pairs (e.g., in1.jsonl:out1.jsonl in2.jsonl:out2.jsonl)')
    
    # Option 3: Input pattern and output file or directory
    input_group.add_argument('-p', '--pattern', nargs=2, metavar=('INPUT_PATTERN', 'OUTPUT'),
                           help='Process all files matching the input pattern (glob) and write to a single output file (if OUTPUT ends with .jsonl) or to separate files in the specified directory')
    
    # Option 4: Input files with automatic output naming
    input_group.add_argument('-i', '--inputs', nargs='+', metavar='INPUT_FILE',
                           help='Process specified input files, automatically generating output filenames (prefixed with "filtered_")')
    
    # Add an argument for number of processes to use
    parser.add_argument('-j', '--jobs', type=int, default=None,
                      help='Number of parallel processes to use. Default is the number of CPU cores.')
    
    # Flag to disable parallel processing
    parser.add_argument('--no-parallel', action='store_true',
                      help='Disable parallel processing')
    
    return parser.parse_args()

def main():
    args = parse_arguments()
    
    # Store all file pairs to process
    file_pairs = []
    
    if args.single:
        # Single file mode
        file_pairs = [(args.single[0], args.single[1])]
    
    elif args.multiple:
        # Multiple file mode with explicit input:output pairs
        for pair in args.multiple:
            try:
                input_file, output_file = pair.split(':', 1)
                file_pairs.append((input_file, output_file))
            except ValueError:
                print(f"Error: Invalid file pair format: {pair}. Should be input:output")
                sys.exit(1)
    
    elif args.pattern:
        # Pattern-based input files with output file or directory
        input_pattern, output = args.pattern
        
        # Expand the glob pattern
        matched_files = glob.glob(input_pattern)
        if not matched_files:
            print(f"Warning: No files found matching pattern '{input_pattern}'")
            print("\nAll processing complete!")
            sys.exit(0)
        
        # Determine if the output is a file or directory
        is_single_output_file = output.endswith('.jsonl')
        
        if is_single_output_file:
            # Single output file mode
            print(f"Will write all processed data to a single output file: {output}")
            
            # Make sure the output directory exists
            output_dir = os.path.dirname(output)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)
            
            # Remove output file if it exists
            if os.path.exists(output):
                os.remove(output)
            
            # Process each input file, appending to the same output
            for i, input_file in enumerate(matched_files):
                file_pairs.append((input_file, output))
                
        else:
            # Directory mode - create output directory if needed
            if not os.path.exists(output):
                os.makedirs(output)
            
            # Create input:output pairs
            for input_file in matched_files:
                output_file = os.path.join(output, f"filtered_{os.path.basename(input_file)}")
                file_pairs.append((input_file, output_file))
    
    elif args.inputs:
        # Multiple input files with automatic output naming
        for input_file in args.inputs:
            output_file = f"filtered_{os.path.basename(input_file)}"
            file_pairs.append((input_file, output_file))
    
    # Determine if we're in single output mode
    single_output_mode = args.pattern and args.pattern[1].endswith('.jsonl')
    
    # Collect statistics
    all_stats = []
    
    # Handle parallel processing based on arguments
    use_parallel = not args.no_parallel and len(file_pairs) > 1
    
    if use_parallel:
        # Determine number of processes to use
        num_processes = args.jobs if args.jobs else min(multiprocessing.cpu_count(), len(file_pairs))
        print(f"Using {num_processes} parallel processes for processing {len(file_pairs)} files")
        
        # For single output file mode, we need to handle concurrent writes carefully
        if single_output_mode:
            # Sequential processing for first file to create the output file
            first_file_pair = file_pairs[0]
            print(f"Processing first file sequentially to initialize output: {first_file_pair[0]} -> {first_file_pair[1]}")
            first_stats = process_file_pair(first_file_pair, single_output_mode, 0, len(file_pairs))
            if first_stats:
                all_stats.append(first_stats)
            
            # Process remaining files in parallel
            remaining_pairs = file_pairs[1:]
            if remaining_pairs:
                with multiprocessing.Pool(processes=num_processes) as pool:
                    process_func = partial(process_file_pair, 
                                         single_output_mode=True)
                    # Create arguments with indices
                    args_with_indices = [(pair, True, i+1, len(file_pairs)) 
                                       for i, pair in enumerate(remaining_pairs)]
                    
                    # Use starmap to pass multiple arguments
                    results = pool.starmap(process_func, args_with_indices)
                    all_stats.extend([r for r in results if r is not None])
        else:
            # Process all files in parallel for non-single output mode
            with multiprocessing.Pool(processes=num_processes) as pool:
                process_func = partial(process_file_pair, 
                                     single_output_mode=False)
                # Create arguments with indices
                args_with_indices = [(pair, False, i, len(file_pairs)) 
                                   for i, pair in enumerate(file_pairs)]
                
                # Use starmap to pass multiple arguments
                results = pool.starmap(process_func, args_with_indices)
                all_stats = [r for r in results if r is not None]
    else:
        # Sequential processing
        for i, file_pair in enumerate(file_pairs):
            stats = process_file_pair(file_pair, single_output_mode, i, len(file_pairs))
            if stats:
                all_stats.append(stats)
    
    # Aggregate and print statistics
    if all_stats:
        if len(all_stats) == 1:
            # Single file processing
            print_statistics(all_stats[0])
        else:
            # Multiple file processing - show combined stats
            print("\n===== Combined Statistics for All Files =====")
            combined_stats = aggregate_statistics(all_stats)
            print_statistics(combined_stats)
    else:
        print("\nNo files were successfully processed.")
    
    print("\nAll processing complete!")

if __name__ == "__main__":
    main() 