#!/usr/bin/env python3
import json
import statistics
from collections import Counter, defaultdict
import argparse
from pathlib import Path


def analyze_results(results_file):
    """Analyze the repository test results from a jsonl file."""
    results = []
    
    with open(results_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line:  # Skip empty lines
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    print(f"Warning: Skipped invalid JSON line: {line[:50]}...")
    
    print(f"Found {len(results)} repository results\n")
    
    # Status analysis
    status_counter = Counter(r["status"] for r in results)
    total = len(results)
    
    print("=== Overall Status Analysis ===")
    for status, count in status_counter.most_common():
        percentage = (count / total) * 100
        print(f"{status}: {count} ({percentage:.2f}%)")
    print()
    
    # Dependency analysis
    deps_found = [r["dependencies"]["found"] for r in results]
    deps_installed = [r["dependencies"]["installed"] for r in results]
    
    print("=== Dependency Analysis ===")
    print("Dependencies found:")
    print(f"  Average: {statistics.mean(deps_found):.2f}")
    print(f"  Median: {statistics.median(deps_found):.2f}")
    print(f"  Max: {max(deps_found)}")
    print(f"  Min: {min(deps_found)}")
    print("Dependencies installed:")
    print(f"  Average: {statistics.mean(deps_installed):.2f}")
    print(f"  Median: {statistics.median(deps_installed):.2f}")
    print(f"  Max: {max(deps_installed)}")
    print(f"  Min: {min(deps_installed)}")
    print()
    
    # Test analysis
    tests_found = sum(r["tests"]["found"] for r in results)
    tests_passed = sum(r["tests"]["passed"] for r in results)
    tests_failed = sum(r["tests"]["failed"] for r in results)
    tests_skipped = sum(r["tests"]["skipped"] for r in results)
    
    print("=== Test Analysis ===")
    print("Tests total:")
    print(f"  Total: {tests_found}")
    print(f"  Average per repo: {tests_found/total:.2f}")
    print(f"  Percentage: {100.00:.2f}%")
    print("Tests passed:")
    print(f"  Total: {tests_passed}")
    print(f"  Average per repo: {tests_passed/total:.2f}")
    percentage_passed = (tests_passed / tests_found * 100) if tests_found > 0 else 0
    print(f"  Percentage: {percentage_passed:.2f}%")
    print("Tests failed:")
    print(f"  Total: {tests_failed}")
    print(f"  Average per repo: {tests_failed/total:.2f}")
    percentage_failed = (tests_failed / tests_found * 100) if tests_found > 0 else 0
    print(f"  Percentage: {percentage_failed:.2f}%")
    print("Tests skipped:")
    print(f"  Total: {tests_skipped}")
    print(f"  Average per repo: {tests_skipped/total:.2f}")
    percentage_skipped = (tests_skipped / tests_found * 100) if tests_found > 0 else 0
    print(f"  Percentage: {percentage_skipped:.2f}%")
    print()
    
    # Execution time analysis
    execution_times = [r["execution"]["elapsed_time"] for r in results if "elapsed_time" in r["execution"]]
    
    print("=== Execution Time Analysis ===")
    print(f"Average execution time: {statistics.mean(execution_times):.2f} seconds")
    print(f"Median execution time: {statistics.median(execution_times):.2f} seconds")
    print(f"Max execution time: {max(execution_times):.2f} seconds")
    print(f"Min execution time: {min(execution_times):.2f} seconds")
    print()
    
    # Error analysis
    error_messages = [r.get("error", "") for r in results if r.get("error")]
    
    # Additional error extraction from logs
    for r in results:
        if "logs" in r:
            for log in r["logs"]:
                if log["level"] == "ERROR":
                    error_messages.append(log["message"])
    
    # Truncate long error messages for better aggregation
    truncated_errors = []
    for error in error_messages:
        if error:
            if len(error) > 100:
                truncated_errors.append(error[:100] + "...")
            else:
                truncated_errors.append(error)
    
    error_counter = Counter(truncated_errors)
    
    print("=== Common Errors ===")
    for error, count in error_counter.most_common(5):
        print(f"Error occurred {count} times: {error}")
    print()
    
    # Log level analysis
    log_levels = defaultdict(int)
    for r in results:
        if "logs" in r:
            for log in r["logs"]:
                log_levels[log["level"]] += 1
    
    print("=== Log Level Analysis ===")
    for level, count in log_levels.items():
        print(f"{level}: {count} messages")
    print()
    
    # Repository type analysis (GitHub vs local)
    github_repos = sum(1 for r in results if "/" in r["repository_identifier"] and "@" in r["repository"])
    local_repos = len(results) - github_repos
    
    print("=== Repository Type Analysis ===")
    print(f"GitHub repositories: {github_repos} ({github_repos/total*100:.2f}%)")
    print(f"Local repositories: {local_repos} ({local_repos/total*100:.2f}%)")
    print()
    
    # Success rate by repository type
    if github_repos > 0:
        github_success = sum(1 for r in results 
                            if "/" in r["repository_identifier"] and "@" in r["repository"] 
                            and r["status"] in ["success", "partial_success"])
        print(f"GitHub repos success rate: {github_success/github_repos*100:.2f}%")
    
    if local_repos > 0:
        local_success = sum(1 for r in results 
                           if not ("/" in r["repository_identifier"] and "@" in r["repository"]) 
                           and r["status"] in ["success", "partial_success"])
        print(f"Local repos success rate: {local_success/local_repos*100:.2f}%")
    print()
    
    # Top dependencies analysis
    dependency_counter = Counter()
    for r in results:
        if "dependencies" in r and "details" in r["dependencies"]:
            for dep in r["dependencies"]["details"]:
                # Extract package name (remove version)
                package = dep.split("==")[0].split(">=")[0].split("<=")[0].strip()
                dependency_counter[package] += 1
    
    print("=== Top Dependencies ===")
    for dep, count in dependency_counter.most_common(10):
        print(f"{dep}: {count} repositories ({count/total*100:.2f}%)")
    print()
    
    # Test execution analysis by status
    status_test_counts = defaultdict(list)
    for r in results:
        status = r["status"]
        status_test_counts[status].append(r["tests"]["found"])
    
    print("=== Tests by Repository Status ===")
    for status, counts in status_test_counts.items():
        if counts:
            avg = statistics.mean(counts)
            print(f"{status}: Average {avg:.2f} tests per repository")
    print()
    
    # Time distribution analysis
    time_distribution = {
        "< 1 min": 0,
        "1-5 min": 0,
        "5-15 min": 0,
        "15-30 min": 0,
        "> 30 min": 0
    }
    
    for r in results:
        time = r["execution"].get("elapsed_time", 0)
        if time < 60:
            time_distribution["< 1 min"] += 1
        elif time < 300:
            time_distribution["1-5 min"] += 1
        elif time < 900:
            time_distribution["5-15 min"] += 1
        elif time < 1800:
            time_distribution["15-30 min"] += 1
        else:
            time_distribution["> 30 min"] += 1
    
    print("=== Execution Time Distribution ===")
    for time_range, count in time_distribution.items():
        print(f"{time_range}: {count} repositories ({count/total*100:.2f}%)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Analyze repository test results')
    parser.add_argument('--results', type=str, default='results.jsonl',
                        help='Path to the results.jsonl file')
    args = parser.parse_args()
    
    results_path = Path(args.results)
    if not results_path.exists():
        print(f"Error: {results_path} not found!")
        exit(1)
    
    analyze_results(results_path)