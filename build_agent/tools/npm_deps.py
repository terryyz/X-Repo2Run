#!/usr/bin/env python3
import subprocess
import json
import sys
import os

def analyze_npm_dependencies():
    """Analyze Node.js project dependencies using npm list."""
    try:
        # Check for package.json
        if not os.path.exists('package.json'):
            print("Error: No package.json found in current directory")
            return 1

        # Run npm list in JSON format with depth limit to avoid huge output
        result = subprocess.run(['npm', 'list', '--json', '--depth=1'], 
                             capture_output=True, 
                             text=True)
        
        # Parse dependencies even if there are peer dependency warnings
        try:
            deps = json.loads(result.stdout)
        except json.JSONDecodeError:
            print("Error parsing npm output")
            return 1

        # Format and display dependencies
        print("\nDependencies found:")
        if 'dependencies' in deps:
            for name, info in deps['dependencies'].items():
                version = info.get('version', 'unknown')
                required = info.get('required', {}).get('version', '')
                print(f"{name}: installed={version}, required={required}")
        
        # Save full dependency tree to file
        with open('npm_dependencies.json', 'w') as f:
            json.dump(deps, f, indent=2)
        print("\nFull dependency tree saved to npm_dependencies.json")
        
        # Return 0 even if there are peer dependency warnings
        return 0
            
    except Exception as e:
        print(f"Error analyzing dependencies: {str(e)}")
        return 1

if __name__ == '__main__':
    sys.exit(analyze_npm_dependencies()) 