#!/usr/bin/env python3
import os
import json
import subprocess
import sys

def analyze_cargo_dependencies():
    """Analyze Rust project dependencies using cargo metadata."""
    try:
        if not os.path.exists("Cargo.toml"):
            print("Error: No Cargo.toml found in current directory")
            return 1
            
        # Run cargo metadata to get dependency information
        cmd = ["cargo", "metadata", "--format-version=1"]
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if process.returncode != 0:
            print(f"Error running cargo metadata: {process.stderr}")
            return process.returncode
            
        # Parse the JSON output
        metadata = json.loads(process.stdout)
        
        # Extract relevant dependency information
        packages = metadata.get("packages", [])
        if not packages:
            print("No packages found in cargo metadata")
            return 1
            
        # Format dependency information
        deps_info = []
        root_package = next((pkg for pkg in packages if pkg.get("source") is None), packages[0])
        
        for dep in root_package.get("dependencies", []):
            dep_info = {
                "name": dep.get("name"),
                "version_req": dep.get("req", "*"),  # version requirement
                "kind": dep.get("kind", "normal"),  # normal, dev, or build dependency
                "optional": dep.get("optional", False)
            }
            deps_info.append(dep_info)
            
        # Save dependencies to JSON file
        with open("cargo_dependencies.json", "w") as f:
            json.dump({"dependencies": deps_info}, f, indent=2)
            
        # Generate dependency graph in DOT format
        dot_content = "digraph dependencies {\n"
        for dep in deps_info:
            dot_content += f'    "{root_package["name"]}" -> "{dep["name"]}" [label="{dep["version_req"]}, {dep["kind"]}"]\n'
        dot_content += "}\n"
        
        with open("dependency.dot", "w") as f:
            f.write(dot_content)
            
        # Print dependencies in readable format
        print("\nDirect dependencies found:")
        for dep in deps_info:
            print(f"{dep['name']} {dep['version_req']} ({dep['kind']})")
            
        print("\nFull dependency tree saved to dependency.dot")
        print("Dependencies information saved to cargo_dependencies.json")
        return 0
        
    except subprocess.TimeoutExpired:
        print("Cargo metadata command timed out")
        return 1
    except json.JSONDecodeError:
        print("Failed to parse cargo metadata output")
        return 1
    except Exception as e:
        print(f"Error analyzing cargo dependencies: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(analyze_cargo_dependencies())