#!/usr/bin/env python3
import subprocess
import sys
import os
import json

def analyze_go_dependencies():
    """Analyze Go project dependencies using go list and go mod graph."""
    try:
        # Check for go.mod
        if not os.path.exists('go.mod'):
            print("Error: No go.mod found in current directory")
            return 1

        # Get direct dependencies
        result = subprocess.run(['go', 'list', '-m', 'all'],
                              capture_output=True,
                              text=True)
        
        if result.returncode != 0:
            print(f"Error running go list: {result.stderr}")
            return 1

        # Parse direct dependencies
        deps = []
        for line in result.stdout.splitlines()[1:]:  # Skip first line (module name)
            parts = line.split()
            if len(parts) >= 2:
                deps.append({
                    'module': parts[0],
                    'version': parts[1] if len(parts) > 1 else 'latest'
                })

        # Get dependency graph
        graph_result = subprocess.run(['go', 'mod', 'graph'],
                                    capture_output=True,
                                    text=True)
        
        if graph_result.returncode == 0:
            # Save dependency graph
            with open('go_dep_graph.txt', 'w') as f:
                f.write(graph_result.stdout)

        # Save dependencies to JSON
        with open('go_dependencies.json', 'w') as f:
            json.dump({'dependencies': deps}, f, indent=2)

        # Print dependencies in readable format
        print("\nDirect dependencies found:")
        for dep in deps:
            print(f"{dep['module']} @ {dep['version']}")
        
        print("\nDependency graph saved to go_dep_graph.txt")
        print("Dependencies information saved to go_dependencies.json")
        return 0
            
    except Exception as e:
        print(f"Error analyzing dependencies: {str(e)}")
        return 1

if __name__ == '__main__':
    sys.exit(analyze_go_dependencies()) 