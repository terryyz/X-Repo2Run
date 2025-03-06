#!/usr/bin/env python3
import subprocess
import sys
import os
import json

def build_go_project():
    """Build a Go project."""
    try:
        # Check for go.mod
        if not os.path.exists('go.mod'):
            print("Error: No go.mod found in current directory")
            return 1

        # Get module info
        try:
            mod_cmd = ['go', 'list', '-m', '-json']
            mod_result = subprocess.run(mod_cmd, capture_output=True, text=True)
            if mod_result.returncode == 0:
                mod_info = json.loads(mod_result.stdout)
                print("Building Go Project:")
                print(f"Module: {mod_info.get('Path', 'N/A')}")
                print(f"Version: {mod_info.get('Version', 'N/A')}")
                print("\nStarting build...\n")
            else:
                print("Warning: Could not get module information")
                
        except Exception as e:
            print(f"Warning: Could not parse module information: {str(e)}")

        # Download dependencies
        print("Downloading dependencies...")
        download_cmd = ['go', 'mod', 'download']
        download_result = subprocess.run(download_cmd, capture_output=True, text=True)
        if download_result.returncode != 0:
            print("Warning: Error downloading dependencies")
            if download_result.stderr:
                print(download_result.stderr, file=sys.stderr)

        # Run Go build
        build_cmd = ['go', 'build', '-v', './...']
        
        # Check for build tags in go.mod directory
        if os.path.exists('build.tags'):
            try:
                with open('build.tags', 'r') as f:
                    tags = f.read().strip()
                    if tags:
                        build_cmd.extend(['-tags', tags])
                        print(f"Using build tags: {tags}")
            except Exception as e:
                print(f"Warning: Could not read build.tags: {str(e)}")
            
        result = subprocess.run(build_cmd, capture_output=True, text=True)
        
        # Print build output
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
            
        # Check for successful build
        if result.returncode == 0:
            # Look for generated binaries
            binaries = []
            for root, _, files in os.walk('.'):
                for file in files:
                    if os.access(os.path.join(root, file), os.X_OK) and not file.endswith('.go'):
                        binaries.append(os.path.join(root, file))
                        
            if binaries:
                print("\nBuild Artifacts:")
                for binary in binaries:
                    print(f"- {binary}")
                    
            print("\nBuild completed successfully!")
        else:
            print("\nBuild failed!")
            
        return result.returncode
            
    except Exception as e:
        print(f"Error building project: {str(e)}")
        return 1

if __name__ == '__main__':
    sys.exit(build_go_project()) 