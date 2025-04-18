#!/usr/bin/env python3
import os
import json
import subprocess

# Sample test results for demonstration
sample_result1 = {
    "repository": "example_repo",
    "status": "failure",
    "test_files": [
        {
            "path": "test_file1.py",
            "tested_files": ["file1.py"],
            "status": "failure",
            "tests": [
                {
                    "name": "test_function1",
                    "classname": "",
                    "status": "error",
                    "message": "collection failure"
                }
            ],
            "summary": {"passed_tests": 0, "failed_tests": 1, "skipped_tests": 0}
        },
        {
            "path": "test_file2.py",
            "tested_files": ["file2.py"],
            "status": "success",
            "tests": [
                {
                    "name": "test_function2",
                    "classname": "",
                    "status": "success",
                    "message": ""
                }
            ],
            "summary": {"passed_tests": 1, "failed_tests": 0, "skipped_tests": 0}
        }
    ],
    "total_summary": {
        "total_files": 2,
        "passed_files": 1,
        "partial_files": 0,
        "failed_files": 1,
        "passed_tests": 1,
        "failed_tests": 1,
        "skipped_tests": 0
    },
    "execution_time": 5.2
}

# Different overall status, different file status, and different test status
sample_result2 = {
    "repository": "example_repo",
    "status": "success",  # Different overall status
    "test_files": [
        {
            "path": "test_file1.py",
            "tested_files": ["file1.py"],
            "status": "success",  # Different file status
            "tests": [
                {
                    "name": "test_function1",
                    "classname": "",
                    "status": "success",  # Different test status
                    "message": ""
                }
            ],
            "summary": {"passed_tests": 1, "failed_tests": 0, "skipped_tests": 0}
        },
        {
            "path": "test_file2.py",
            "tested_files": ["file2.py"],
            "status": "success",
            "tests": [
                {
                    "name": "test_function2",
                    "classname": "",
                    "status": "success",
                    "message": ""
                }
            ],
            "summary": {"passed_tests": 1, "failed_tests": 0, "skipped_tests": 0}
        },
        {
            "path": "test_file3.py",  # New test file only in result2
            "tested_files": ["file3.py"],
            "status": "success",
            "tests": [
                {
                    "name": "test_function3",
                    "classname": "",
                    "status": "success",
                    "message": ""
                }
            ],
            "summary": {"passed_tests": 1, "failed_tests": 0, "skipped_tests": 0}
        }
    ],
    "total_summary": {
        "total_files": 3,
        "passed_files": 3,
        "partial_files": 0,
        "failed_files": 0,
        "passed_tests": 3,
        "failed_tests": 0,
        "skipped_tests": 0
    },
    "execution_time": 6.1
}

# Another repository only in first result
sample_result3 = {
    "repository": "unique_repo_1",
    "status": "success",
    "test_files": [
        {
            "path": "test_unique.py",
            "tested_files": ["unique.py"],
            "status": "success",
            "tests": [
                {
                    "name": "test_unique_function",
                    "classname": "",
                    "status": "success",
                    "message": ""
                }
            ],
            "summary": {"passed_tests": 1, "failed_tests": 0, "skipped_tests": 0}
        }
    ],
    "total_summary": {
        "total_files": 1,
        "passed_files": 1,
        "partial_files": 0,
        "failed_files": 0,
        "passed_tests": 1,
        "failed_tests": 0,
        "skipped_tests": 0
    },
    "execution_time": 3.4
}

# Another repository only in second result
sample_result4 = {
    "repository": "unique_repo_2",
    "status": "failure",
    "test_files": [
        {
            "path": "test_unique2.py",
            "tested_files": ["unique2.py"],
            "status": "failure",
            "tests": [
                {
                    "name": "test_unique_function2",
                    "classname": "",
                    "status": "failure",
                    "message": "AssertionError"
                }
            ],
            "summary": {"passed_tests": 0, "failed_tests": 1, "skipped_tests": 0}
        }
    ],
    "total_summary": {
        "total_files": 1,
        "passed_files": 0,
        "partial_files": 0,
        "failed_files": 1,
        "passed_tests": 0,
        "failed_tests": 1,
        "skipped_tests": 0
    },
    "execution_time": 2.8
}

# Create sample JSONL files
def create_sample_files():
    # Create first JSONL file
    with open("sample_result1.jsonl", "w") as f:
        f.write(json.dumps(sample_result1) + "\n")
        f.write(json.dumps(sample_result3) + "\n")  # Add unique repo to first file
    
    # Create second JSONL file
    with open("sample_result2.jsonl", "w") as f:
        f.write(json.dumps(sample_result2) + "\n")
        f.write(json.dumps(sample_result4) + "\n")  # Add unique repo to second file
    
    print("Created sample JSONL files:")
    print("  - sample_result1.jsonl")
    print("  - sample_result2.jsonl")

def run_comparison():
    cmd = ["python", "compare_test_results.py", "sample_result1.jsonl", "sample_result2.jsonl", "--output", "sample_comparison.json"]
    print(f"Running command: {' '.join(cmd)}")
    subprocess.run(cmd)
    
    print("\nComparison complete. Results saved to sample_comparison.json")
    print("You can examine the detailed results in that file.")

def cleanup():
    for file in ["sample_result1.jsonl", "sample_result2.jsonl", "sample_comparison.json"]:
        if os.path.exists(file):
            os.remove(file)
    print("\nCleaned up sample files.")

def main():
    print("=== Test Results Comparison Example ===\n")
    
    # Create sample files
    create_sample_files()
    
    # Run comparison
    run_comparison()
    
    # Ask if user wants to clean up
    response = input("\nClean up sample files? (y/n): ")
    if response.lower() == 'y':
        cleanup()
    else:
        print("\nSample files retained for your review.")

if __name__ == "__main__":
    main() 