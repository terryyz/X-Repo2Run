#!/usr/bin/env python3
"""
Script to add a "group" key to tests in a JSONL file, mapping tested modules 
(functions/methods/classes) to their corresponding test names.
"""

import json
import sys
import os
import ast
from collections import defaultdict
from tqdm import tqdm
import multiprocessing
from functools import partial
import time

def extract_test_cases(test_content):
    """
    Extract test class and method names from test content using AST
    Returns a list of tuples (test_class_name, test_method_name)
    """
    test_cases = []
    
    try:
        # Parse the test content with AST
        tree = ast.parse(test_content)
        
        # Find test classes
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                class_name = node.name
                
                # Look for methods starting with 'test_'
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name.startswith('test_'):
                        method_name = item.name
                        test_cases.append((class_name, method_name))
        
        # If no test classes found, look for standalone test functions
        if not test_cases:
            for node in tree.body:
                if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
                    method_name = node.name
                    test_cases.append(('TestModule', method_name))  # Use a dummy class name
    
    except SyntaxError:
        pass
    
    return test_cases

def parse_target_file(file_path):
    """
    Parse the target file to extract function, method, and class names
    """
    if not os.path.exists(file_path):
        return [], [], {}
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read()
        
        try:
            tree = ast.parse(source)
            
            functions = []
            classes = []
            methods = defaultdict(list)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # Check if it's a method or a function
                    if hasattr(node, 'parent_class'):
                        methods[node.parent_class].append(node.name)
                    else:
                        functions.append(node.name)
                elif isinstance(node, ast.ClassDef):
                    classes.append(node.name)
                    # Mark methods with their parent class
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            item.parent_class = node.name
                            methods[node.name].append(item.name)
            
            return functions, classes, methods
        except SyntaxError:
            return [], [], {}
    except Exception:
        return [], [], {}

def extract_imports(test_content):
    """
    Extract imported modules and functions/classes from the test content using AST
    """
    imported_items = []
    
    try:
        tree = ast.parse(test_content)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    imported_items.append((None, name.name))
            elif isinstance(node, ast.ImportFrom):
                module = node.module
                for name in node.names:
                    if name.name == '*':
                        imported_items.append((module, '*'))
                    else:
                        imported_items.append((module, name.name))
    
    except SyntaxError:
        pass
    
    return imported_items

def analyze_test_case(test_class, test_method, test_content, target_file, target_entities):
    """
    Analyze a test case to determine which entities from the target file it tests using AST
    """
    functions, classes, methods = target_entities
    
    tested_entities = []
    
    try:
        # Parse the test content
        tree = ast.parse(test_content)
        
        # Find the method definition
        method_node = None
        class_node = None
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == test_class:
                class_node = node
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == test_method:
                        method_node = item
                        break
                if method_node:
                    break
        
        # If not found in a class, look for standalone function
        if not method_node:
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == test_method:
                    method_node = node
                    break
        
        if not method_node:
            return []
        
        # Extract references in the method body
        references = set()
        for node in ast.walk(method_node):
            if isinstance(node, ast.Name):
                references.add(node.id)
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                references.add(f"{node.value.id}.{node.attr}")
        
        # Check if any function from the target file is directly referenced
        for func in functions:
            if func in references:
                tested_entities.append(func)
        
        # Check for class references
        for cls in classes:
            if cls in references:
                tested_entities.append(cls)
                # Also check for method calls on this class
                for method in methods[cls]:
                    if f"{cls}.{method}" in references:
                        tested_entities.append(f"{cls}.{method}")
        
        # If no direct references found, use method name heuristics
        if not tested_entities:
            # Remove 'test_' prefix to guess the function name
            if test_method.startswith('test_'):
                possible_func = test_method[5:]
                if possible_func in functions:
                    tested_entities.append(possible_func)
            
            # Check for class name in test class name
            for cls in classes:
                if cls in test_class:
                    tested_entities.append(cls)
        
        # If still no matches, use imported module analysis
        if not tested_entities:
            # Get the basename of the target file without extension
            target_basename = os.path.basename(target_file)
            if '.' in target_basename:
                target_basename = target_basename.rsplit('.', 1)[0]
            
            imports = extract_imports(test_content)
            for module, item in imports:
                # Check if the import might be related to the target file
                if module and (target_basename in module or module.endswith(target_basename)):
                    if item == '*':
                        # If we imported everything, all functions and classes are candidates
                        tested_entities.extend(functions)
                        tested_entities.extend(classes)
                    elif item in functions:
                        tested_entities.append(item)
                    elif item in classes:
                        tested_entities.append(item)
    
    except SyntaxError:
        pass
    
    return tested_entities

def process_line(line, repository_base_path=""):
    """
    Process a single line from the JSONL file
    Returns the processed line as a string
    """
    try:
        data = json.loads(line.strip())
        repository_path = data.get("repository", repository_base_path)
        
        # Process each test in the "tests" section
        if "tests" in data:
            # Check if "tests" is a dictionary
            if isinstance(data["tests"], dict):
                # Iterate over the tests dictionary items
                for test_key, test_info in data["tests"].items():
                    # Initialize group if not present
                    if "group" not in test_info:
                        test_info["group"] = {}
                    
                    # Process the test content and add tested entities to groups
                    if "content" in test_info:
                        test_content_list = test_info["content"]
                        
                        # The test_key is the tested file path, we may need to concatenate with repository path
                        tested_file = repository_path + "/" + test_key
                        
                        # Collect all test cases from all content strings
                        all_test_cases = []
                        for j, content in enumerate(test_content_list):
                            test_cases = extract_test_cases(content)
                            for test_class, test_method in test_cases:
                                all_test_cases.append((j, test_class, test_method, content))
                        
                        # Process the target file (which is the test_key)
                        
                        # Extract entities from the target file
                        target_entities = parse_target_file(tested_file)
                        
                        # Collect all test cases and their names for potential fallback grouping
                        all_test_names = []
                        
                        # Analyze each test case
                        for j, test_class, test_method, content in all_test_cases:
                            tested_entities = analyze_test_case(
                                test_class, test_method, content, tested_file, target_entities
                            )
                            
                            # Store test name for potential fallback grouping
                            test_name = f"{j}.{test_class}.{test_method}"
                            all_test_names.append(test_name)
                            
                            # Add the test case to the group dictionary
                            for entity in tested_entities:
                                if entity not in test_info["group"]:
                                    test_info["group"][entity] = []
                                if test_name not in test_info["group"][entity]:
                                    test_info["group"][entity].append(test_name)
                        
                        # If no entities were found for any test case, create a fallback group using the tested file
                        if not test_info["group"] and all_test_names:
                            # Use just the basename to avoid path issues
                            file_basename = os.path.basename(tested_file)
                            test_info["group"][file_basename] = all_test_names
                    
                    # Update the test in the data dictionary
                    data["tests"][test_key] = test_info
            elif isinstance(data["tests"], list):
                # Iterate over the tests list items
                for i, test_info in enumerate(data["tests"]):
                    # Initialize group if not present
                    if isinstance(test_info, dict):
                        if "group" not in test_info:
                            test_info["group"] = {}
                        
                        # Process the test content and add tested entities to groups
                        if "content" in test_info and "file" in test_info:
                            test_content_list = test_info["content"]
                            tested_file = test_info["file"]  # The "file" field contains the tested file
                            
                            # Collect all test cases from all content strings
                            all_test_cases = []
                            for j, content in enumerate(test_content_list):
                                test_cases = extract_test_cases(content)
                                for test_class, test_method in test_cases:
                                    all_test_cases.append((j, test_class, test_method, content))
                            
                            # Process the target file
                            
                            # Extract entities from the target file
                            target_entities = parse_target_file(tested_file)
                            
                            # Collect all test cases and their names for potential fallback grouping
                            all_test_names = []
                            
                            # Analyze each test case
                            for j, test_class, test_method, content in all_test_cases:
                                tested_entities = analyze_test_case(
                                    test_class, test_method, content, tested_file, target_entities
                                )
                                
                                # Store test name for potential fallback grouping
                                test_name = f"{j}.{test_class}.{test_method}"
                                all_test_names.append(test_name)
                                
                                # Add the test case to the group dictionary
                                for entity in tested_entities:
                                    if entity not in test_info["group"]:
                                        test_info["group"][entity] = []
                                    if test_name not in test_info["group"][entity]:
                                        test_info["group"][entity].append(test_name)
                        
                            # If no entities were found for any test case, create a fallback group using the tested file
                            if not test_info["group"] and all_test_names:
                                # Use just the basename to avoid path issues
                                file_basename = os.path.basename(tested_file)
                                test_info["group"][file_basename] = all_test_names
                        elif "content" in test_info and "path" in test_info:
                            test_content_list = test_info["content"]
                            tested_file = test_info["path"]  # The "path" field contains the tested file
                            
                            # Collect all test cases from all content strings
                            all_test_cases = []
                            for j, content in enumerate(test_content_list):
                                test_cases = extract_test_cases(content)
                                for test_class, test_method in test_cases:
                                    all_test_cases.append((j, test_class, test_method, content))
                            
                            # Process the target file
                            
                            # Extract entities from the target file
                            target_entities = parse_target_file(tested_file)
                            
                            # Collect all test cases and their names for potential fallback grouping
                            all_test_names = []
                            
                            # Analyze each test case
                            for j, test_class, test_method, content in all_test_cases:
                                tested_entities = analyze_test_case(
                                    test_class, test_method, content, tested_file, target_entities
                                )
                                
                                # Store test name for potential fallback grouping
                                test_name = f"{j}.{test_class}.{test_method}"
                                all_test_names.append(test_name)
                                
                                # Add the test case to the group dictionary
                                for entity in tested_entities:
                                    if entity not in test_info["group"]:
                                        test_info["group"][entity] = []
                                    if test_name not in test_info["group"][entity]:
                                        test_info["group"][entity].append(test_name)
                            
                            # If no entities were found for any test case, create a fallback group using the tested file
                            if not test_info["group"] and all_test_names:
                                # Use just the basename to avoid path issues
                                file_basename = os.path.basename(tested_file)
                                test_info["group"][file_basename] = all_test_names
                        
                        # Update the test in the data dictionary
                        data["tests"][i] = test_info
        
        # Return the processed line
        return json.dumps(data)
    except json.JSONDecodeError:
        return None
    except Exception:
        return None

def process_chunk(chunk, chunk_id, total_chunks, temp_dir, repository_base_path=""):
    """
    Process a chunk of lines from the JSONL file
    """
    output_file = f"{temp_dir}/chunk_{chunk_id}.jsonl"
    processed_tests = 0
    
    # Create temp dir if it doesn't exist
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
    
    # Create a progress bar for this chunk
    desc = f"Chunk {chunk_id+1}/{total_chunks}"
    with tqdm(total=len(chunk), desc=desc, unit="lines", position=chunk_id) as pbar:
        with open(output_file, 'w', encoding='utf-8') as f:
            for line in chunk:
                processed_line = process_line(line, repository_base_path)
                if processed_line:
                    f.write(processed_line + '\n')
                    processed_tests += 1
                
                pbar.update(1)
                pbar.set_postfix(processed_tests=processed_tests)
    
    return output_file

def process_jsonl_file_parallel(input_file, output_file, num_processes=None):
    """
    Process a JSONL file in parallel, adding a "group" key to each test
    """
    # Determine the number of processes to use
    if num_processes is None:
        num_processes = multiprocessing.cpu_count()
    
    print(f"Using {num_processes} processes for parallel processing")
    
    # Make sure the output directory exists
    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Remove output file if it exists
    if os.path.exists(output_file):
        os.remove(output_file)
    
    # Create a temporary directory for intermediate files
    temp_dir = f"{output_dir if output_dir else '.'}/temp_{int(time.time())}"
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
    
    # Count total lines for preprocessing
    print("Counting lines in input file...")
    total_lines = sum(1 for _ in open(input_file, 'r', encoding='utf-8', errors='replace'))
    print(f"Total lines: {total_lines}")
    
    # Read all lines to memory for distribution to workers
    print("Reading input file...")
    with open(input_file, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    
    # Distribute lines into chunks for parallel processing
    chunk_size = max(1, len(lines) // num_processes)
    chunks = [lines[i:i + chunk_size] for i in range(0, len(lines), chunk_size)]
    total_chunks = len(chunks)
    print(f"Dividing data into {total_chunks} chunks")
    
    # Try to get repository base path from the first valid line
    repository_base_path = ""
    for line in lines[:10]:  # Check first 10 lines
        try:
            data = json.loads(line.strip())
            if "repository" in data:
                repository_base_path = data["repository"]
                break
        except:
            continue
    
    # Process chunks in parallel
    print(f"Processing {total_chunks} chunks in parallel...")
    
    # Initialize multiprocessing pool
    pool = multiprocessing.Pool(processes=num_processes)
    
    # Define the worker function with fixed arguments
    worker_func = partial(process_chunk, 
                          total_chunks=total_chunks, 
                          temp_dir=temp_dir,
                          repository_base_path=repository_base_path)
    
    # Submit all chunks for processing
    chunk_futures = []
    for i, chunk in enumerate(chunks):
        chunk_futures.append((i, pool.apply_async(worker_func, (chunk, i))))
    
    # Wait for all chunks to complete and collect results
    temp_files = []
    for i, future in chunk_futures:
        try:
            temp_file = future.get()
            temp_files.append(temp_file)
        except Exception as e:
            print(f"Error processing chunk {i}: {e}")
    
    # Close and join the pool
    pool.close()
    pool.join()
    
    # Merge all temporary files into the output file
    print("Merging results...")
    with open(output_file, 'w', encoding='utf-8') as out_f:
        for temp_file in temp_files:
            if os.path.exists(temp_file):
                with open(temp_file, 'r', encoding='utf-8') as in_f:
                    for line in in_f:
                        out_f.write(line)
    
    # Clean up temporary files
    print("Cleaning up temporary files...")
    for temp_file in temp_files:
        if os.path.exists(temp_file):
            os.remove(temp_file)
    
    if os.path.exists(temp_dir):
        try:
            os.rmdir(temp_dir)
        except:
            pass
    
    print(f"Parallel processing complete. Results written to {output_file}")

def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} input_file output_file")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    print(f"Processing {input_file} -> {output_file}")
    start_time = time.time()
    process_jsonl_file_parallel(input_file, output_file)
    end_time = time.time()
    print(f"Done processing! Time taken: {end_time - start_time:.2f} seconds")

if __name__ == "__main__":
    # Set up multiprocessing to spawn rather than fork on Unix-based systems
    # This helps avoid any potential issues with forking
    multiprocessing.set_start_method('spawn', force=True)
    main()