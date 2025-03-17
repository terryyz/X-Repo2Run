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
Simple UV Example - Demonstrates the straightforward approach to using UV

This script shows how to:
1. Install UV using pip
2. Create a virtual environment with uv venv
3. Install packages with uv pip install

Usage:
    python uv_simple_example.py
"""

import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path

def install_uv():
    """Install UV using pip."""
    print("=== Installing UV using pip ===")
    try:
        # Check if UV is already installed
        result = subprocess.run('uv --version', shell=True, check=False, text=True, capture_output=True)
        if result.returncode == 0:
            print(f"UV is already installed: {result.stdout.strip()}")
            return True
        
        # Install UV using pip
        print("Installing UV...")
        result = subprocess.run('pip install uv', shell=True, check=True, text=True, capture_output=True)
        print("UV installed successfully.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to install UV: {e.stderr}")
        return False

def create_venv(venv_path='.venv'):
    """Create a virtual environment using uv venv."""
    print(f"\n=== Creating virtual environment at {venv_path} ===")
    try:
        result = subprocess.run(['uv', 'venv', venv_path], check=True, text=True, capture_output=True)
        print(f"Virtual environment created at {venv_path}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to create virtual environment: {e.stderr}")
        return False

def install_packages(packages, venv_path='.venv'):
    """Install packages using uv pip install."""
    print(f"\n=== Installing packages: {', '.join(packages)} ===")
    
    # Get the path to the Python executable in the virtual environment
    if sys.platform == 'win32':
        python_path = os.path.join(venv_path, 'Scripts', 'python.exe')
    else:
        python_path = os.path.join(venv_path, 'bin', 'python')
    
    try:
        cmd = ['uv', 'pip', 'install', '--python', python_path]
        cmd.extend(packages)
        
        result = subprocess.run(cmd, check=True, text=True, capture_output=True)
        print(f"Packages installed successfully: {', '.join(packages)}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to install packages: {e.stderr}")
        return False

def run_script(script_content, venv_path='.venv'):
    """Create and run a Python script in the virtual environment."""
    print("\n=== Creating and running a test script ===")
    
    # Create a temporary script file
    script_path = 'test_script.py'
    with open(script_path, 'w') as f:
        f.write(script_content)
    
    # Get the path to the Python executable in the virtual environment
    if sys.platform == 'win32':
        python_path = os.path.join(venv_path, 'Scripts', 'python.exe')
    else:
        python_path = os.path.join(venv_path, 'bin', 'python')
    
    try:
        cmd = ['uv', 'run', '--python', python_path, 'python', script_path]
        print(f"Running script with command: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True, text=True)
        os.remove(script_path)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to run script: {e}")
        os.remove(script_path)
        return False

def main():
    # Create a temporary directory for our example
    temp_dir = tempfile.mkdtemp(prefix="uv_simple_example_")
    print(f"Working in temporary directory: {temp_dir}")
    
    # Change to the temporary directory
    original_dir = os.getcwd()
    os.chdir(temp_dir)
    
    try:
        # Step 1: Install UV
        if not install_uv():
            print("Failed to install UV. Exiting.")
            return False
        
        # Step 2: Create a virtual environment
        if not create_venv():
            print("Failed to create virtual environment. Exiting.")
            return False
        
        # Step 3: Install some packages
        packages = ['requests', 'numpy', 'rich']
        if not install_packages(packages):
            print("Failed to install packages. Exiting.")
            return False
        
        # Step 4: Create and run a test script
        script_content = """
import requests
import numpy as np
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
    
    console.print("[bold green]\\nAll packages were installed and imported successfully![/bold green]")

if __name__ == "__main__":
    main()
"""
        if not run_script(script_content):
            print("Failed to run test script. Exiting.")
            return False
        
        print("\n=== Example completed successfully! ===")
        print(f"Temporary directory: {temp_dir}")
        print("You can explore the files and environment created in this directory.")
        print("When you're done, you can delete this directory to clean up.")
        
        return True
    
    except Exception as e:
        print(f"An error occurred: {e}")
        return False
    
    finally:
        # Change back to the original directory
        os.chdir(original_dir)

if __name__ == "__main__":
    success = main()
    if not success:
        sys.exit(1) 