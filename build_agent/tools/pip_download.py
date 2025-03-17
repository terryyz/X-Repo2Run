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

import subprocess
import argparse
import warnings
import sys
import os
warnings.simplefilter('ignore', FutureWarning)

def check_uv_installed():
    """Check if UV is installed, and install it if not."""
    try:
        result = subprocess.run('uv --version', shell=True, check=False, text=True, capture_output=True)
        if result.returncode == 0:
            print(f"UV is installed: {result.stdout.strip()}")
            return True
    except Exception:
        pass
    
    print("UV is not installed. Installing UV using pip...")
    try:
        # Install UV using pip
        install_cmd = 'pip install uv'
        result = subprocess.run(install_cmd, shell=True, check=True, text=True, capture_output=True)
        print("UV installed successfully via pip.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to install UV: {e.stderr.strip()}")
        return False

def run_package_install(package_name, version_constraints, venv_path=".venv"):
    """Install a package using UV in a virtual environment.
    
    Args:
        package_name: Name of the package to install
        version_constraints: Version constraints for the package
        venv_path: Path to the virtual environment
    """
    if not check_uv_installed():
        print("UV is required to install packages. Installation failed.")
        return False
    
    # Create full package name with version constraints
    if not version_constraints or len(version_constraints.strip()) == 0:
        full_name = package_name
    else:
        full_name = package_name + version_constraints
    
    # Create virtual environment if it doesn't exist
    if not os.path.exists(venv_path):
        print(f"Creating virtual environment at {venv_path}...")
        try:
            result = subprocess.run(['uv', 'venv', venv_path], check=True, text=True, capture_output=True)
            print(f"Virtual environment created at {venv_path}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to create virtual environment: {e.stderr}")
            return False
    
    # Install the package using UV
    try:
        print(f"Installing {full_name} using UV...")
        cmd = ['uv', 'pip', 'install', full_name, '--python', os.path.join(venv_path, 'bin', 'python')]
        result = subprocess.run(cmd, check=True, text=True, capture_output=True)
        print(f"The package {full_name} was installed successfully.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to install the package {full_name}: {e.stderr}")
        return False

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Install a Python package with UV.')
    parser.add_argument('-p', '--package_name', required=True, type=str, help='The name of the package to install.')
    parser.add_argument('-v', '--version_constraints', type=str, default='', nargs='?', help='The version constraints of the package.')
    parser.add_argument('--venv', type=str, default='.venv', help='Path to the virtual environment.')
    args = parser.parse_args()

    success = run_package_install(args.package_name, args.version_constraints, args.venv)
    if not success:
        sys.exit(1)
    else:
        sys.exit(0)