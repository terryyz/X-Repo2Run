#!/usr/bin/env python3
import subprocess
import sys
import os
import json
import toml

def build_rust_project():
    """Build a Rust project using Cargo."""
    try:
        # Check for Cargo.toml
        if not os.path.exists('Cargo.toml'):
            print("Error: No Cargo.toml found in current directory")
            return 1

        # Parse Cargo.toml to get project info
        try:
            with open('Cargo.toml', 'r') as f:
                cargo_toml = toml.load(f)
            
            package_info = cargo_toml.get('package', {})
            print("Building Rust Project:")
            print(f"Name: {package_info.get('name', 'N/A')}")
            print(f"Version: {package_info.get('version', 'N/A')}")
            print(f"Authors: {', '.join(package_info.get('authors', ['N/A']))}")
            print("\nStarting build...\n")
            
        except Exception as e:
            print(f"Warning: Could not parse Cargo.toml: {str(e)}")

        # Run Cargo build
        build_cmd = ['cargo', 'build', '--release']
        
        # Check for target directory override
        if os.path.exists('.cargo/config.toml'):
            try:
                with open('.cargo/config.toml', 'r') as f:
                    cargo_config = toml.load(f)
                    if 'build' in cargo_config and 'target-dir' in cargo_config['build']:
                        print(f"Using custom target directory: {cargo_config['build']['target-dir']}")
            except Exception as e:
                print(f"Warning: Could not parse .cargo/config.toml: {str(e)}")
            
        result = subprocess.run(build_cmd, capture_output=True, text=True)
        
        # Print build output
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
            
        # Check for successful build
        if result.returncode == 0:
            # Look for generated artifacts
            target_dir = 'target/release'
            if os.path.exists(target_dir):
                # Get binary name from Cargo.toml
                binary_name = package_info.get('name', '')
                if binary_name:
                    binary_path = os.path.join(target_dir, binary_name)
                    if os.path.exists(binary_path):
                        print(f"\nBuild Artifact:")
                        print(f"- {binary_path}")
                        
                    # Check for additional targets
                    if 'bin' in cargo_toml:
                        for binary in cargo_toml['bin']:
                            if 'name' in binary:
                                bin_path = os.path.join(target_dir, binary['name'])
                                if os.path.exists(bin_path):
                                    print(f"- {bin_path}")
                                    
            print("\nBuild completed successfully!")
        else:
            print("\nBuild failed!")
            
        return result.returncode
            
    except Exception as e:
        print(f"Error building project: {str(e)}")
        return 1

if __name__ == '__main__':
    sys.exit(build_rust_project()) 