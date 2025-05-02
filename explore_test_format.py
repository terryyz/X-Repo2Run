#!/usr/bin/env python3
"""
Script to add a "group" key to tests in a JSONL file, mapping tested modules 
(functions/methods/classes) to their corresponding test names.
"""

import json
import sys
import re
import os
import ast
import logging
from collections import defaultdict
import pprint

# Configure logging - more verbose
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def extract_test_cases(test_content):
    """
    Extract test class and method names from test content
    Returns a list of tuples (test_class_name, test_method_name)
    """
    test_cases = []
    
    # Use regex to find test classes
    class_matches = re.finditer(r'class\s+(\w+)(?:\s*\([^)]*\))?:', test_content)
    for class_match in class_matches:
        class_name = class_match.group(1)
        # logger.debug(f"Found test class: {class_name}")
        
        # Find the class body
        class_start = class_match.start()
        next_class = re.search(r'class\s+\w+(?:\s*\([^)]*\))?:', test_content[class_start+1:])
        class_end = next_class.start() + class_start + 1 if next_class else len(test_content)
        class_body = test_content[class_start:class_end]
        
        # Look for methods starting with 'test_'
        method_pattern = r'def\s+(test_\w+)\s*\('
        method_matches = re.finditer(method_pattern, class_body)
        for method_match in method_matches:
            method_name = method_match.group(1)
            # logger.debug(f"Found test method: {class_name}.{method_name}")
            test_cases.append((class_name, method_name))
    
    # If no test classes found, look for standalone test functions
    if not test_cases:
        # logger.debug("No test classes found, searching for standalone test functions")
        method_pattern = r'def\s+(test_\w+)\s*\('
        method_matches = re.finditer(method_pattern, test_content)
        for method_match in method_matches:
            method_name = method_match.group(1)
            # logger.debug(f"Found standalone test function: {method_name}")
            test_cases.append(('TestModule', method_name))  # Use a dummy class name
    
    # logger.info(f"Extracted {len(test_cases)} test cases")
    return test_cases

def parse_target_file(file_path):
    """
    Parse the target file to extract function, method, and class names
    """
    # logger.info(f"Parsing target file: {file_path}")
    
    if not os.path.exists(file_path):
        logger.warning(f"Target file {file_path} does not exist")
        return [], [], {}
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read()
            # logger.debug(f"Successfully read {len(source)} bytes from {file_path}")
        
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
                        # logger.debug(f"Found method: {node.parent_class}.{node.name}")
                    else:
                        functions.append(node.name)
                        # logger.debug(f"Found function: {node.name}")
                elif isinstance(node, ast.ClassDef):
                    classes.append(node.name)
                    # logger.debug(f"Found class: {node.name}")
                    # Mark methods with their parent class
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            item.parent_class = node.name
                            methods[node.name].append(item.name)
                            # logger.debug(f"Found method: {node.name}.{item.name}")
            
            # logger.info(f"AST parsing found: {len(functions)} functions, {len(classes)} classes, {sum(len(m) for m in methods.values())} methods")
            return functions, classes, methods
        except SyntaxError as e:
            # Fall back to regex-based parsing if AST parsing fails
            logger.warning(f"AST parsing failed for {file_path} with error: {e}, falling back to regex")
            return parse_target_file_with_regex(source)
    except Exception as e:
        logger.error(f"Error reading {file_path}: {e}")
        return [], [], {}

def parse_target_file_with_regex(source):
    """
    Parse the target file using regex when AST parsing fails
    """
    # logger.info("Using regex-based parsing fallback")
    functions = []
    classes = []
    methods = defaultdict(list)
    
    # Find all classes
    class_matches = re.finditer(r'class\s+(\w+)(?:\s*\([^)]*\))?:', source)
    for class_match in class_matches:
        class_name = class_match.group(1)
        classes.append(class_name)
        # logger.debug(f"Regex found class: {class_name}")
        
        # Find the class body
        class_start = class_match.start()
        next_class = re.search(r'class\s+\w+(?:\s*\([^)]*\))?:', source[class_start+1:])
        class_end = next_class.start() + class_start + 1 if next_class else len(source)
        class_body = source[class_start:class_end]
        
        # Find methods in the class
        method_matches = re.finditer(r'def\s+(\w+)\s*\(', class_body)
        for method_match in method_matches:
            method_name = method_match.group(1)
            if method_name != '__init__':  # Skip constructor
                methods[class_name].append(method_name)
                # logger.debug(f"Regex found method: {class_name}.{method_name}")
    
    # Find standalone functions
    function_matches = re.finditer(r'(?:^|\n)def\s+(\w+)\s*\(', source)
    for function_match in function_matches:
        function_name = function_match.group(1)
        # Check if this is a method we already found
        is_method = False
        for class_methods in methods.values():
            if function_name in class_methods:
                is_method = True
                break
        
        if not is_method:
            functions.append(function_name)
            # logger.debug(f"Regex found function: {function_name}")
    
    # logger.info(f"Regex parsing found: {len(functions)} functions, {len(classes)} classes, {sum(len(m) for m in methods.values())} methods")
    return functions, classes, methods

def extract_imports(test_content):
    """
    Extract imported modules and functions/classes from the test content
    """
    imported_items = []
    
    # Match 'from X import Y' style imports
    from_imports = re.finditer(r'from\s+(\S+)\s+import\s+([\w,\s*]+)', test_content)
    for match in from_imports:
        module = match.group(1)
        items = match.group(2).split(',')
        for item in items:
            item = item.strip()
            if item == '*':
                imported_items.append((module, '*'))
                # logger.debug(f"Found wildcard import: from {module} import *")
            else:
                imported_items.append((module, item))
                # logger.debug(f"Found import: from {module} import {item}")
    
    # Match 'import X' style imports
    direct_imports = re.finditer(r'import\s+([\w.,\s]+)', test_content)
    for match in direct_imports:
        imports = match.group(1).split(',')
        for imp in imports:
            imp = imp.strip()
            if '.' in imp:
                parts = imp.split('.')
                module = '.'.join(parts[:-1])
                item = parts[-1]
                imported_items.append((module, item))
                # logger.debug(f"Found import: from {module} import {item}")
            else:
                imported_items.append((None, imp))
                # logger.debug(f"Found import: import {imp}")
    
    # logger.info(f"Extracted {len(imported_items)} imports")
    return imported_items

def analyze_test_case(test_class, test_method, test_content, target_file, target_entities):
    """
    Analyze a test case to determine which entities from the target file it tests
    """
    # logger.info(f"Analyzing test case: {test_class}.{test_method} for {target_file}")
    functions, classes, methods = target_entities
    
    # Find the method implementation
    method_pattern = f'def\s+{test_method}\s*\([^)]*\):([^$]*?)(?:(?:def|class)\s|\Z)'
    method_match = re.search(method_pattern, test_content, re.DOTALL)
    
    if not method_match:
        logger.warning(f"Could not find implementation for test method: {test_method}")
        return []
    
    method_body = method_match.group(1)
    tested_entities = []
    
    # Extract imports to help with identifying tested modules
    imports = extract_imports(test_content)
    
    # Check if any function from the target file is directly referenced
    for func in functions:
        if re.search(rf'\b{re.escape(func)}\b', method_body):
            tested_entities.append(func)
            # logger.debug(f"Found direct reference to function: {func}")
    
    # Check for class references
    for cls in classes:
        # Check for direct class references
        if re.search(rf'\b{re.escape(cls)}\b', method_body):
            tested_entities.append(cls)
            # logger.debug(f"Found direct reference to class: {cls}")
            # Also check for method calls on this class
            for method in methods[cls]:
                if re.search(rf'\b{re.escape(cls)}\.{re.escape(method)}\b', method_body):
                    tested_entities.append(f"{cls}.{method}")
                    # logger.debug(f"Found direct reference to method: {cls}.{method}")
    
    # If no direct references found, use method name heuristics
    if not tested_entities:
        # logger.debug("No direct references found, using heuristics")
        # Remove 'test_' prefix to guess the function name
        if test_method.startswith('test_'):
            possible_func = test_method[5:]
            if possible_func in functions:
                tested_entities.append(possible_func)
                # logger.debug(f"Found function match by name heuristic: {possible_func}")
        
        # Check for class name in test class name
        for cls in classes:
            if cls in test_class:
                tested_entities.append(cls)
                # logger.debug(f"Found class match by name heuristic: {cls}")
    
    # If still no matches, use imported module analysis
    if not tested_entities:
        # logger.debug("No matches from heuristics, using import analysis")
        # Get the basename of the target file without extension
        target_basename = os.path.basename(target_file)
        if '.' in target_basename:
            target_basename = target_basename.rsplit('.', 1)[0]
        
        for module, item in imports:
            # Check if the import might be related to the target file
            if module and (target_basename in module or module.endswith(target_basename)):
                if item == '*':
                    # If we imported everything, all functions and classes are candidates
                    tested_entities.extend(functions)
                    tested_entities.extend(classes)
                    # logger.debug(f"Added all {len(functions)} functions and {len(classes)} classes due to wildcard import")
                elif item in functions:
                    tested_entities.append(item)
                    # logger.debug(f"Found function match by import: {item}")
                elif item in classes:
                    tested_entities.append(item)
                    # logger.debug(f"Found class match by import: {item}")
    
    # logger.info(f"Found {len(tested_entities)} tested entities: {', '.join(tested_entities)}")
    return tested_entities

def process_jsonl_file(input_file, output_file):
    """
    Process a JSONL file, adding a "group" key to each test
    """
    # logger.info(f"Processing JSONL file: {input_file} -> {output_file}")
    
    # Make sure the output directory exists
    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
        # logger.info(f"Created output directory: {output_dir}")
    
    # Remove output file if it exists
    if os.path.exists(output_file):
        os.remove(output_file)
        # logger.info(f"Removed existing output file: {output_file}")
    
    processed_lines = 0
    processed_tests = 0
    
    with open(input_file, 'r', encoding='utf-8', errors='replace') as f:
        line_number = 0
        for line in f:
            line_number += 1
            processed_lines += 1
            # logger.info(f"Processing line {line_number}")
            
            try:
                data = json.loads(line.strip())
                # # logger.debug(f"Data structure before processing: {pprint.pformat(data)}")
                repository_path = data["repository"]
                # Process each test in the "tests" section
                if "tests" in data:
                    # logger.info(f"Found 'tests' section with {len(data['tests'])} entries")
                    
                    # Check if "tests" is a dictionary
                    if isinstance(data["tests"], dict):
                        # logger.info("Tests is a dictionary")
                        # Iterate over the tests dictionary items
                        for test_key, test_info in data["tests"].items():
                            # logger.info(f"Processing test: {test_key}")
                            # # logger.debug(f"Test info: {pprint.pformat(test_info)}")
                            
                            # Initialize group if not present
                            if "group" not in test_info:
                                test_info["group"] = {}
                                # logger.debug(f"Added empty 'group' key to test {test_key}")
                            
                            # Process the test content and add tested entities to groups
                            # logger.debug(f"Test info keys: {test_info.keys()}")
                            if "content" in test_info:
                                test_content_list = test_info["content"]
                                
                                # The test_key is the tested file path, we may need to concatenate with repository path
                                tested_file = repository_path + "/" + test_key
                                # if "path" in test_info and test_info["path"] == test_key:
                                    # If a path field exists and matches test_key, it confirms this is a relative path
                                    # logger.debug(f"Found path field matching test_key: {test_key}")
                                
                                # logger.info(f"Test has {len(test_content_list)} content strings, tested file is {tested_file}")
                                
                                # Collect all test cases from all content strings
                                all_test_cases = []
                                for j, content in enumerate(test_content_list):
                                    # logger.info(f"Extracting test cases from content[{j}]")
                                    test_cases = extract_test_cases(content)
                                    for test_class, test_method in test_cases:
                                        all_test_cases.append((j, test_class, test_method, content))
                                
                                # logger.info(f"Found {len(all_test_cases)} test cases across all content strings")
                                
                                # Process the target file (which is the test_key)
                                # logger.info(f"Processing target file: {tested_file}")
                                
                                # Extract entities from the target file
                                target_entities = parse_target_file(tested_file)
                                print(tested_file)
                                # Analyze each test case
                                for j, test_class, test_method, content in all_test_cases:
                                    # logger.info(f"Analyzing test case: content[{j}].{test_class}.{test_method}")
                                    tested_entities = analyze_test_case(
                                        test_class, test_method, content, tested_file, target_entities
                                    )
                                    
                                    # Add the test case to the group dictionary
                                    for entity in tested_entities:
                                        if entity not in test_info["group"]:
                                            test_info["group"][entity] = []
                                        test_name = f"{j}.{test_class}.{test_method}"
                                        if test_name not in test_info["group"][entity]:
                                            test_info["group"][entity].append(test_name)
                                            # logger.debug(f"Added {test_name} to group[{entity}]")
                                
                                # logger.info(f"Completed processing test {test_key} with {len(test_info['group'])} groups")
                            else:
                                logger.warning(f"Test {test_key} missing required field: content")
                            
                            # Update the test in the data dictionary
                            data["tests"][test_key] = test_info
                            processed_tests += 1
                    elif isinstance(data["tests"], list):
                        # logger.info("Tests is a list")
                        # Iterate over the tests list items
                        for i, test_info in enumerate(data["tests"]):
                            # logger.info(f"Processing test at index {i}")
                            # # logger.debug(f"Test info: {pprint.pformat(test_info)}")
                            
                            # Initialize group if not present
                            if isinstance(test_info, dict):
                                if "group" not in test_info:
                                    test_info["group"] = {}
                                    # logger.debug(f"Added empty 'group' key to test at index {i}")
                                
                                # Process the test content and add tested entities to groups
                                if "content" in test_info and "file" in test_info:
                                    test_content_list = test_info["content"]
                                    tested_file = test_info["file"]  # The "file" field contains the tested file
                                    
                                    # logger.info(f"Test has {len(test_content_list)} content strings, tested file is {tested_file}")
                                    
                                    # Collect all test cases from all content strings
                                    all_test_cases = []
                                    for j, content in enumerate(test_content_list):
                                        # logger.info(f"Extracting test cases from content[{j}]")
                                        test_cases = extract_test_cases(content)
                                        for test_class, test_method in test_cases:
                                            all_test_cases.append((j, test_class, test_method, content))
                                    
                                    # logger.info(f"Found {len(all_test_cases)} test cases across all content strings")
                                    
                                    # Process the target file
                                    # logger.info(f"Processing target file: {tested_file}")
                                    
                                    # Extract entities from the target file
                                    target_entities = parse_target_file(tested_file)
                                    
                                    # Analyze each test case
                                    for j, test_class, test_method, content in all_test_cases:
                                        # logger.info(f"Analyzing test case: content[{j}].{test_class}.{test_method}")
                                        tested_entities = analyze_test_case(
                                            test_class, test_method, content, tested_file, target_entities
                                        )
                                        
                                        # Add the test case to the group dictionary
                                        for entity in tested_entities:
                                            if entity not in test_info["group"]:
                                                test_info["group"][entity] = []
                                            test_name = f"{j}.{test_class}.{test_method}"
                                            if test_name not in test_info["group"][entity]:
                                                test_info["group"][entity].append(test_name)
                                                # logger.debug(f"Added {test_name} to group[{entity}]")
                                    
                                    # logger.info(f"Completed processing test at index {i} with {len(test_info['group'])} groups")
                                elif "content" in test_info and "path" in test_info:
                                    test_content_list = test_info["content"]
                                    tested_file = test_info["path"]  # The "path" field contains the tested file
                                    
                                    # logger.info(f"Test has {len(test_content_list)} content strings, tested file is {tested_file}")
                                    
                                    # Collect all test cases from all content strings
                                    all_test_cases = []
                                    for j, content in enumerate(test_content_list):
                                        # logger.info(f"Extracting test cases from content[{j}]")
                                        test_cases = extract_test_cases(content)
                                        for test_class, test_method in test_cases:
                                            all_test_cases.append((j, test_class, test_method, content))
                                    
                                    # logger.info(f"Found {len(all_test_cases)} test cases across all content strings")
                                    
                                    # Process the target file
                                    # logger.info(f"Processing target file: {tested_file}")
                                    
                                    # Extract entities from the target file
                                    target_entities = parse_target_file(tested_file)
                                    
                                    # Analyze each test case
                                    for j, test_class, test_method, content in all_test_cases:
                                        # logger.info(f"Analyzing test case: content[{j}].{test_class}.{test_method}")
                                        tested_entities = analyze_test_case(
                                            test_class, test_method, content, tested_file, target_entities
                                        )
                                        
                                        # Add the test case to the group dictionary
                                        for entity in tested_entities:
                                            if entity not in test_info["group"]:
                                                test_info["group"][entity] = []
                                            test_name = f"{j}.{test_class}.{test_method}"
                                            if test_name not in test_info["group"][entity]:
                                                test_info["group"][entity].append(test_name)
                                                # logger.debug(f"Added {test_name} to group[{entity}]")
                                    
                                    # logger.info(f"Completed processing test at index {i} with {len(test_info['group'])} groups")
                                else:
                                    logger.warning(f"Test at index {i} missing required fields: content, path, or file")
                                
                                # Update the test in the data dictionary
                                data["tests"][i] = test_info
                                processed_tests += 1
                            else:
                                logger.warning(f"Test at index {i} is not a dictionary: {type(test_info)}")
                    else:
                        logger.warning(f"Tests is neither a list nor a dictionary: {type(data['tests'])}")
                
                # # logger.debug(f"Data structure after processing: {pprint.pformat(data)}")
                
                # Write the modified data to the output file
                # logger.info("Writing modified data to output file")
                with open(output_file, 'a', encoding='utf-8') as out_f:
                    out_f.write(json.dumps(data) + '\n')
            except json.JSONDecodeError:
                logger.error(f"Error parsing JSON at line {line_number}: {line.strip()}")
            except Exception as e:
                logger.error(f"Error processing line {line_number}: {str(e)}", exc_info=True)
    
    # logger.info(f"Processing complete: processed {processed_lines} lines and {processed_tests} tests")
    
    # After processing, print out a sample of the output file to verify
    try:
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            with open(output_file, 'r', encoding='utf-8') as f:
                sample_data = json.loads(f.readline().strip())
                # # logger.info(f"Sample output data: {pprint.pformat(sample_data)}")
    except Exception as e:
        logger.error(f"Error reading sample output: {str(e)}")

def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} input_file output_file")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    # logger.info(f"Starting processing: {input_file} -> {output_file}")
    process_jsonl_file(input_file, output_file)
    # logger.info("Processing complete")

if __name__ == "__main__":
    main() 