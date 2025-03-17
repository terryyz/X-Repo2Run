#!/usr/bin/env python3
# Copyright (2025) Bytedance Ltd. and/or its affiliates 

# Licensed under the Apache License, Version 2.0 (the "License"); 
# you may not use this file except in compliance with the License. 
# You may obtain a copy of the License at 

#     https://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software 
# distributed under the License is distributed on an "AS IS" BASIS, 
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. 
# See the License for the specific language governing permissions and 
# limitations under the License. 

"""
UV Example Script - Demonstrates how to use UV for a Python project

This script shows how to:
1. Check if UV is installed
2. Create a new Python environment
3. Install dependencies
4. Run a Python script in the environment
5. Export requirements

Usage:
    python uv_example.py
"""

import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path

# Import the UV environment management functions
try:
    from uv_environment import (
        check_uv_installed,
        create_environment,
        install_dependencies,
        run_in_environment,
        export_requirements
    )
except ImportError:
    print("Error: uv_environment.py not found. Make sure it's in the same directory.")
    sys.exit(1)

def create_example_project():
    """Create a simple example project to demonstrate UV."""
    # Create a temporary directory for our example project
    project_dir = tempfile.mkdtemp(prefix="uv_example_")
    print(f"Created example project directory: {project_dir}")
    
    # Change to the project directory
    os.chdir(project_dir)
    
    # Create a simple Python script
    with open("example_script.py", "w") as f:
        f.write("""
import requests
import numpy as np
import matplotlib.pyplot as plt
from rich.console import Console

console = Console()

def main():
    # Make a request to a public API
    response = requests.get("https://jsonplaceholder.typicode.com/posts/1")
    data = response.json()
    
    # Create some random data with numpy
    x = np.linspace(0, 10, 100)
    y = np.sin(x)
    
    # Print the data with rich
    console.print("[bold green]API Response:[/bold green]")
    console.print(data)
    
    console.print("[bold green]\\nNumPy Array:[/bold green]")
    console.print(f"Created array with shape: {x.shape}")
    
    # Create a simple plot
    plt.figure(figsize=(8, 4))
    plt.plot(x, y)
    plt.title("Sine Wave")
    plt.savefig("sine_wave.png")
    plt.close()
    
    console.print("[bold green]\\nCreated plot:[/bold green] sine_wave.png")

if __name__ == "__main__":
    main()
""")
    
    # Create a requirements.txt file
    with open("requirements.txt", "w") as f:
        f.write("""
requests==2.31.0
numpy==1.26.4
matplotlib==3.8.3
rich==13.7.0
""")
    
    return project_dir

def run_example():
    """Run the UV example workflow."""
    # Check if UV is installed
    if not check_uv_installed():
        print("Failed to install UV. Exiting.")
        return False
    
    # Create an example project
    project_dir = create_example_project()
    print(f"\nWorking in project directory: {project_dir}")
    
    try:
        # Create a virtual environment
        print("\n=== Creating a virtual environment ===")
        if not create_environment(env_path=".venv", python_version=None):
            print("Failed to create virtual environment. Exiting.")
            return False
        
        # Install dependencies from requirements.txt
        print("\n=== Installing dependencies ===")
        if not install_dependencies(requirements_file="requirements.txt", env_path=".venv"):
            print("Failed to install dependencies. Exiting.")
            return False
        
        # Run the example script
        print("\n=== Running the example script ===")
        if not run_in_environment(["python", "example_script.py"], env_path=".venv"):
            print("Failed to run the example script. Exiting.")
            return False
        
        # Export the requirements
        print("\n=== Exporting requirements ===")
        if not export_requirements(env_path=".venv", output_file="exported_requirements.txt"):
            print("Failed to export requirements. Exiting.")
            return False
        
        # Show the exported requirements
        print("\n=== Exported Requirements ===")
        with open("exported_requirements.txt", "r") as f:
            print(f.read())
        
        print("\n=== Example completed successfully! ===")
        print(f"Project directory: {project_dir}")
        print("You can explore the files and environment created in this directory.")
        print("When you're done, you can delete this directory to clean up.")
        
        return True
    
    except Exception as e:
        print(f"An error occurred: {e}")
        return False

if __name__ == "__main__":
    success = run_example()
    if not success:
        sys.exit(1) 