#!/usr/bin/env python3
import subprocess
import sys
import os
import json
import xml.etree.ElementTree as ET

def run_junit_tests():
    """Run Java tests using JUnit."""
    try:
        # Check for Maven or Gradle build
        is_maven = os.path.exists('pom.xml')
        is_gradle = os.path.exists('build.gradle') or os.path.exists('build.gradle.kts')
        
        if not (is_maven or is_gradle):
            print("Error: No pom.xml or build.gradle found in current directory")
            return 1

        if is_maven:
            # Run Maven tests
            result = subprocess.run(['mvn', 'test', '-B'],
                                 capture_output=True,
                                 text=True)
            
            # Check if no tests were found
            if "No tests were found" in result.stdout or "No tests to run" in result.stdout:
                print("No unit tests were detected in this repository, so it passes. Congratulations, you have successfully configured the environment!")
                return 0
                
            # Parse surefire reports
            surefire_dir = 'target/surefire-reports'
            if os.path.exists(surefire_dir):
                parse_surefire_reports(surefire_dir)
                
        else:
            # Run Gradle tests
            result = subprocess.run(['./gradlew', 'test', '--console=plain'],
                                 capture_output=True,
                                 text=True)
                                 
            # Check if no tests were found
            if "No tests found" in result.stdout or "UP-TO-DATE" in result.stdout:
                print("No unit tests were detected in this repository, so it passes. Congratulations, you have successfully configured the environment!")
                return 0
                
            # Parse Gradle test reports
            test_report_dir = 'build/test-results/test'
            if os.path.exists(test_report_dir):
                parse_surefire_reports(test_report_dir)  # Same format as surefire

        # Print test output
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
            
        return result.returncode
            
    except Exception as e:
        print(f"Error running tests: {str(e)}")
        return 1

def parse_surefire_reports(report_dir):
    """Parse JUnit XML test reports."""
    total_tests = 0
    failures = 0
    errors = 0
    skipped = 0
    time = 0.0
    
    failed_tests = []
    
    for file in os.listdir(report_dir):
        if file.endswith('.xml'):
            try:
                tree = ET.parse(os.path.join(report_dir, file))
                root = tree.getroot()
                
                # Get test suite stats
                total_tests += int(root.get('tests', 0))
                failures += int(root.get('failures', 0))
                errors += int(root.get('errors', 0))
                skipped += int(root.get('skipped', 0))
                time += float(root.get('time', 0))
                
                # Collect failed test details
                for testcase in root.findall('.//testcase'):
                    failure = testcase.find('failure')
                    error = testcase.find('error')
                    if failure is not None or error is not None:
                        failed_tests.append({
                            'class': testcase.get('classname'),
                            'test': testcase.get('name'),
                            'message': (failure or error).get('message'),
                            'type': (failure or error).get('type')
                        })
                        
            except ET.ParseError as e:
                print(f"Warning: Could not parse {file}: {str(e)}")
                continue
    
    # Print summary
    print("\nTest Summary:")
    print(f"Total Tests: {total_tests}")
    print(f"Passed: {total_tests - failures - errors - skipped}")
    print(f"Failed: {failures}")
    print(f"Errors: {errors}")
    print(f"Skipped: {skipped}")
    print(f"Time: {time:.2f}s")
    
    # Print failed test details
    if failed_tests:
        print("\nFailed Tests:")
        for test in failed_tests:
            print(f"\n{test['class']}.{test['test']}")
            print(f"Type: {test['type']}")
            print(f"Message: {test['message']}")

if __name__ == '__main__':
    sys.exit(run_junit_tests()) 