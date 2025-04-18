#!/usr/bin/env python3
import json
import argparse
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Any

def load_jsonl(file_path: str) -> List[Dict]:
    """Load data from a JSONL file."""
    data = []
    with open(file_path, 'r') as f:
        for line in f:
            data.append(json.loads(line.strip()))
    return data

def get_repo_map(data: List[Dict]) -> Dict[str, Dict]:
    """Create a map of repository name to its test results."""
    repo_map = {}
    for entry in data:
        repo_name = entry.get("repository")
        if repo_name:
            repo_map[repo_name] = entry
    return repo_map

def compare_test_status(test1: Dict, test2: Dict) -> bool:
    """Compare two test results to check if they are the same."""
    return (
        test1.get("status") == test2.get("status") and
        test1.get("message") == test2.get("message")
    )

def analyze_test_file_differences(test_file1: Dict, test_file2: Dict) -> Dict:
    """Analyze differences between two test files."""
    result = {
        "status_different": test_file1.get("status") != test_file2.get("status"),
        "test_count_different": False,
        "test_differences": []
    }
    
    tests1 = {test["name"]: test for test in test_file1.get("tests", [])}
    tests2 = {test["name"]: test for test in test_file2.get("tests", [])}
    
    # Check if test counts are different
    result["test_count_different"] = len(tests1) != len(tests2)
    
    # Find tests in file1 but not in file2
    for name, test in tests1.items():
        if name not in tests2:
            result["test_differences"].append({
                "name": name,
                "only_in": "file1",
                "status": test.get("status"),
                "message": test.get("message")
            })
        elif not compare_test_status(test, tests2[name]):
            result["test_differences"].append({
                "name": name,
                "in_both": True,
                "file1_status": test.get("status"),
                "file1_message": test.get("message"),
                "file2_status": tests2[name].get("status"),
                "file2_message": tests2[name].get("message")
            })
    
    # Find tests in file2 but not in file1
    for name, test in tests2.items():
        if name not in tests1:
            result["test_differences"].append({
                "name": name,
                "only_in": "file2",
                "status": test.get("status"),
                "message": test.get("message")
            })
    
    return result

def compare_repos(repo_data1: Dict, repo_data2: Dict) -> Dict:
    """Compare test results for a single repository."""
    result = {
        "repository": repo_data1.get("repository"),
        "status_same": repo_data1.get("status") == repo_data2.get("status"),
        "status1": repo_data1.get("status"),
        "status2": repo_data2.get("status"),
        "execution_time1": repo_data1.get("execution_time"),
        "execution_time2": repo_data2.get("execution_time"),
        "test_file_differences": []
    }
    
    # Get test files from both results
    test_files1 = {tf["path"]: tf for tf in repo_data1.get("test_files", [])}
    test_files2 = {tf["path"]: tf for tf in repo_data2.get("test_files", [])}
    all_paths = set(test_files1.keys()) | set(test_files2.keys())
    
    # Compare each test file
    for path in all_paths:
        difference = {
            "path": path,
        }
        
        if path in test_files1 and path in test_files2:
            difference["in_both"] = True
            difference["status_same"] = test_files1[path].get("status") == test_files2[path].get("status")
            difference["status1"] = test_files1[path].get("status")
            difference["status2"] = test_files2[path].get("status")
            difference["analysis"] = analyze_test_file_differences(test_files1[path], test_files2[path])
        else:
            difference["in_both"] = False
            difference["only_in"] = "file1" if path in test_files1 else "file2"
            difference["status"] = test_files1[path].get("status") if path in test_files1 else test_files2[path].get("status")
        
        result["test_file_differences"].append(difference)
    
    return result

def main():
    parser = argparse.ArgumentParser(description="Compare two test result JSONL files")
    parser.add_argument("file1", help="Path to the first JSONL file")
    parser.add_argument("file2", help="Path to the second JSONL file")
    parser.add_argument("--output", help="Path to output JSON file", default="comparison_results.json")
    args = parser.parse_args()
    
    # Load data from both files
    data1 = load_jsonl(args.file1)
    data2 = load_jsonl(args.file2)
    
    # Create repository maps
    repo_map1 = get_repo_map(data1)
    repo_map2 = get_repo_map(data2)
    
    # Find repos in both files
    common_repos = set(repo_map1.keys()) & set(repo_map2.keys())
    only_in_file1 = set(repo_map1.keys()) - set(repo_map2.keys())
    only_in_file2 = set(repo_map2.keys()) - set(repo_map1.keys())
    
    # Compare common repositories
    results = {
        "common_repos_count": len(common_repos),
        "only_in_file1_count": len(only_in_file1),
        "only_in_file2_count": len(only_in_file2),
        "common_repos_with_different_status": 0,
        "common_repos_with_same_status_but_differences": 0,
        "repo_comparisons": []
    }
    
    for repo in common_repos:
        comparison = compare_repos(repo_map1[repo], repo_map2[repo])
        results["repo_comparisons"].append(comparison)
        
        if not comparison["status_same"]:
            results["common_repos_with_different_status"] += 1
        elif any(not diff["in_both"] or not diff["status_same"] for diff in comparison["test_file_differences"]):
            results["common_repos_with_same_status_but_differences"] += 1
    
    # Write results to file
    with open(args.output, 'w') as f:
        json.dump(results, f, indent=2)
    
    # Print summary
    print(f"Comparison complete. Found {len(common_repos)} repositories in both files.")
    print(f"  - {results['common_repos_with_different_status']} repos have different overall status")
    print(f"  - {results['common_repos_with_same_status_but_differences']} repos have same status but differences in test files")
    print(f"  - {len(only_in_file1)} repos are only in the first file")
    print(f"  - {len(only_in_file2)} repos are only in the second file")
    print(f"Detailed results written to {args.output}")
    
    # Print detailed information about differences
    print("\nRepositories with different status:")
    for comparison in results["repo_comparisons"]:
        if not comparison["status_same"]:
            print(f"  - {comparison['repository']}: {comparison['status1']} vs {comparison['status2']}")
            
            # Find test files that caused the difference
            for diff in comparison["test_file_differences"]:
                if not diff["in_both"] or not diff.get("status_same", True):
                    if diff["in_both"]:
                        print(f"    - Test file: {diff['path']} (status: {diff['status1']} vs {diff['status2']})")
                    else:
                        print(f"    - Test file: {diff['path']} (only in {'first' if diff['only_in'] == 'file1' else 'second'} file)")

    print("\nRepositories with same status but different test results:")
    for comparison in results["repo_comparisons"]:
        if comparison["status_same"] and any(not diff["in_both"] or not diff.get("status_same", True) for diff in comparison["test_file_differences"]):
            print(f"  - {comparison['repository']} (status: {comparison['status1']})")
            
            for diff in comparison["test_file_differences"]:
                if not diff["in_both"]:
                    print(f"    - Test file: {diff['path']} (only in {'first' if diff['only_in'] == 'file1' else 'second'} file)")
                elif not diff.get("status_same", True):
                    print(f"    - Test file: {diff['path']} (status: {diff['status1']} vs {diff['status2']})")

if __name__ == "__main__":
    main() 