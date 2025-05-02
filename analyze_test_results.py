import json
from collections import Counter
from typing import Dict, List

def analyze_test_results(file_path: str):
    # Counters for statistics
    repo_status_counts = Counter()
    total_tests = {"passed": 0, "failed": 0, "skipped": 0}
    file_status_counts = Counter()  # New counter for file statuses
    total_repos = 0
    total_test_files = 0
    successful_repos = []  # List to track successful repositories
    
    # Read and process the JSONL file
    with open(file_path, 'r') as f:
        for line in f:
            data = json.loads(line.strip())
            total_repos += 1
            
            # Count repository status
            repo_status_counts[data['status']] += 1
            
            # Track successful repositories
            if data['status'] == 'success':
                repo_name = data.get('repository', f"Repository #{total_repos}")
                successful_repos.append(repo_name)
            
            # Process test files
            test_files = data.get('test_files', [])
            total_test_files += len(test_files)
            
            # Count file statuses
            for test_file in test_files:
                file_status_counts[test_file.get('status', 'unknown')] += 1
            
            # Get test summary from total_summary
            summary = data.get('total_summary', {})
            total_tests['passed'] += summary.get('passed_tests', 0)
            total_tests['failed'] += summary.get('failed_tests', 0)
            total_tests['skipped'] += summary.get('skipped_tests', 0)
    
    # Print analysis results
    print("\n=== Repository Test Analysis ===")
    print("\nRepository Status Distribution:")
    for status, count in repo_status_counts.items():
        percentage = (count / total_repos) * 100
        print(f"- {status}: {count} ({percentage:.1f}%)")
    
    print("\nTest Statistics:")
    print(f"Total repositories analyzed: {total_repos}")
    print(f"Total test files: {total_test_files}")
    
    print("\nTest File Status Distribution:")
    for status, count in file_status_counts.items():
        percentage = (count / total_test_files) * 100 if total_test_files > 0 else 0
        print(f"- {status}: {count} ({percentage:.1f}%)")
    
    print("\nTest Results:")
    total_all_tests = sum(total_tests.values())
    for test_type, count in total_tests.items():
        if total_all_tests > 0:
            percentage = (count / total_all_tests) * 100
            print(f"- {test_type}: {count} ({percentage:.1f}%)")
        else:
            print(f"- {test_type}: {count} (0.0%)")
    
    # Print repositories with success status
    print("\nRepositories with Success Status:")
    if successful_repos:
        for repo in successful_repos:
            print(f"- {repo}")
    else:
        print("No repositories with success status found.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python analyze_test_results.py <path_to_jsonl_file>")
        sys.exit(1)
    
    analyze_test_results(sys.argv[1])