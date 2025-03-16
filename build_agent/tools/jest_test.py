#!/usr/bin/env python3
import subprocess
import sys
import os
import json

def run_jest_tests():
    """Run JavaScript/TypeScript tests using Jest."""
    try:
        # Check for package.json
        if not os.path.exists('package.json'):
            print("Error: No package.json found in current directory")
            return 1
        
                # Run Jest tests
        test_cmd = ['npm', 'test', '--', '--json', '--outputFile=jest-results.json']
        if os.path.exists('jest.config.js') or os.path.exists('jest.config.ts') or os.path.exists('jest.config.mjs'):
            test_cmd.extend(['--config', 'jest.config.js' if os.path.exists('jest.config.js') else 'jest.config.ts' if os.path.exists('jest.config.ts') else 'jest.config.mjs'])
        else:
            print("No unit tests were detected in this repository, so it passes. Congratulations, you have successfully configured the environment!")
            return 0
        
        # Check if Jest is available
        with open('package.json') as f:
            package_json = json.load(f)
            has_jest = False
            
            # Check dependencies and devDependencies for Jest
            if 'dependencies' in package_json and 'jest' in package_json['dependencies']:
                has_jest = True
            if 'devDependencies' in package_json and 'jest' in package_json['devDependencies']:
                has_jest = True
            
            # Check if there's a test script using Jest
            if 'scripts' in package_json and 'test' in package_json['scripts']:
                if 'jest' in package_json['scripts']['test']:
                    has_jest = True

        if not has_jest:
            print("Jest not found in package.json. Installing Jest...")
            install_result = subprocess.run(['npm', 'install', '--save-dev', 'jest'],
                                         capture_output=True,
                                         text=True)
            if install_result.returncode != 0:
                print(f"Error installing Jest: {install_result.stderr}")
                return 1

        
        result = subprocess.run(test_cmd, capture_output=True, text=True)
        
        # Check if no tests were found
        if "Could not find a config file" in result.stdout or "Could not find a config file" in result.stderr or "No tests found" in result.stdout or "No tests found" in result.stderr:
            print("No unit tests were detected in this repository, so it passes. Congratulations, you have successfully configured the environment!")
            return 0
            
        # Parse and display test results
        if os.path.exists('jest-results.json'):
            try:
                with open('jest-results.json') as f:
                    results = json.load(f)
                    print("\nTest Results:")
                    print(f"Total Tests: {results.get('numTotalTests', 0)}")
                    print(f"Passed: {results.get('numPassedTests', 0)}")
                    print(f"Failed: {results.get('numFailedTests', 0)}")
                    print(f"Time: {results.get('testResults', [{}])[0].get('perfStats', {}).get('runtime', 0)}ms")
                    
                    # Print failed test details
                    if results.get('numFailedTests', 0) > 0:
                        print("\nFailed Tests:")
                        for test_file in results.get('testResults', []):
                            for test in test_file.get('assertionResults', []):
                                if test.get('status') == 'failed':
                                    print(f"\n{test.get('fullName', 'Unknown Test')}")
                                    print(f"Error: {test.get('failureMessages', ['No error message'])[0]}")
            except json.JSONDecodeError:
                print("Error parsing test results")
                
        return result.returncode
            
    except Exception as e:
        print(f"Error running tests: {str(e)}")
        return 1

if __name__ == '__main__':
    sys.exit(run_jest_tests()) 