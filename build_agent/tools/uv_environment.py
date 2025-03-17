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
from pathlib import Path
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

def create_environment(env_path=None, python_version=None):
    """Create a new Python virtual environment using UV.
    
    Args:
        env_path: Path to create the environment at. If None, creates in .venv
        python_version: Python version to use. If None, uses the latest available
    """
    if not check_uv_installed():
        print("UV is required to create environments. Installation failed.")
        return False
    
    # Build the command
    cmd = ['uv', 'venv']
    
    if env_path:
        cmd.append(env_path)
    
    if python_version:
        cmd.extend(['--python', python_version])
    
    try:
        print(f"Creating virtual environment with command: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True, text=True, capture_output=True)
        print(result.stdout)
        
        # Get the path to the created environment
        venv_path = env_path if env_path else '.venv'
        
        print(f"Virtual environment created successfully at: {venv_path}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to create virtual environment: {e.stderr}")
        return False

def install_dependencies(requirements_file=None, packages=None, env_path=None):
    """Install dependencies into a virtual environment using UV.
    
    Args:
        requirements_file: Path to requirements.txt file
        packages: List of packages to install
        env_path: Path to the virtual environment. If None, uses .venv
    """
    if not check_uv_installed():
        print("UV is required to install dependencies. Installation failed.")
        return False
    
    if not requirements_file and not packages:
        print("Either requirements_file or packages must be provided.")
        return False
    
    # Determine the environment path
    venv_path = env_path if env_path else '.venv'
    
    # Create the environment if it doesn't exist
    if not os.path.exists(venv_path):
        if not create_environment(venv_path):
            return False
    
    # Get the path to the Python executable in the virtual environment
    if sys.platform == 'win32':
        python_path = os.path.join(venv_path, 'Scripts', 'python.exe')
    else:
        python_path = os.path.join(venv_path, 'bin', 'python')
    
    # Build the command
    if requirements_file:
        cmd = ['uv', 'pip', 'install', '-r', requirements_file, '--python', python_path]
        
        try:
            print(f"Installing dependencies from {requirements_file} with command: {' '.join(cmd)}")
            result = subprocess.run(cmd, check=True, text=True, capture_output=True)
            print(result.stdout)
            return True
        except subprocess.CalledProcessError as e:
            print(f"Failed to install dependencies: {e.stderr}")
            return False
    
    if packages:
        cmd = ['uv', 'pip', 'install', '--python', python_path]
        cmd.extend(packages)
        
        try:
            print(f"Installing packages {', '.join(packages)} with command: {' '.join(cmd)}")
            result = subprocess.run(cmd, check=True, text=True, capture_output=True)
            print(result.stdout)
            return True
        except subprocess.CalledProcessError as e:
            print(f"Failed to install packages: {e.stderr}")
            return False
    
    return False

def run_in_environment(command, env_path=None):
    """Run a command in the specified virtual environment.
    
    Args:
        command: Command to run
        env_path: Path to the virtual environment. If None, uses .venv
    """
    if not check_uv_installed():
        print("UV is required to run commands in environments. Installation failed.")
        return False
    
    # Determine the environment path
    venv_path = env_path if env_path else '.venv'
    
    # Create the environment if it doesn't exist
    if not os.path.exists(venv_path):
        if not create_environment(venv_path):
            return False
    
    # Build the command
    cmd = ['uv', 'run']
    
    # Get the path to the Python executable in the virtual environment
    if sys.platform == 'win32':
        python_path = os.path.join(venv_path, 'Scripts', 'python.exe')
    else:
        python_path = os.path.join(venv_path, 'bin', 'python')
    
    cmd.extend(['--python', python_path])
    
    # Add the command to run
    cmd.extend(command if isinstance(command, list) else command.split())
    
    try:
        print(f"Running command in environment: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to run command: {e}")
        return False

def export_requirements(env_path=None, output_file='requirements.txt'):
    """Export installed packages to a requirements.txt file.
    
    Args:
        env_path: Path to the virtual environment. If None, uses .venv
        output_file: Path to the output requirements file
    """
    if not check_uv_installed():
        print("UV is required to export requirements. Installation failed.")
        return False
    
    # Determine the environment path
    venv_path = env_path if env_path else '.venv'
    
    # Get the path to the Python executable in the virtual environment
    if sys.platform == 'win32':
        python_path = os.path.join(venv_path, 'Scripts', 'python.exe')
    else:
        python_path = os.path.join(venv_path, 'bin', 'python')
    
    # Build the command
    cmd = ['uv', 'pip', 'freeze', '--python', python_path]
    
    try:
        print(f"Exporting requirements with command: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True, text=True, capture_output=True)
        
        # Write the output to the requirements file
        with open(output_file, 'w') as f:
            f.write(result.stdout)
        
        print(f"Requirements exported to {output_file}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to export requirements: {e.stderr}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Manage Python environments with UV.')
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Create environment command
    create_parser = subparsers.add_parser('create', help='Create a new virtual environment')
    create_parser.add_argument('--path', type=str, help='Path to create the environment at')
    create_parser.add_argument('--python', type=str, help='Python version to use')
    
    # Install dependencies command
    install_parser = subparsers.add_parser('install', help='Install dependencies')
    install_parser.add_argument('--requirements', type=str, help='Path to requirements.txt file')
    install_parser.add_argument('--packages', type=str, nargs='+', help='Packages to install')
    install_parser.add_argument('--env', type=str, help='Path to the virtual environment')
    
    # Run command
    run_parser = subparsers.add_parser('run', help='Run a command in the virtual environment')
    run_parser.add_argument('command_args', type=str, nargs='+', help='Command to run')
    run_parser.add_argument('--env', type=str, help='Path to the virtual environment')
    
    # Export requirements command
    export_parser = subparsers.add_parser('export', help='Export installed packages to a requirements.txt file')
    export_parser.add_argument('--env', type=str, help='Path to the virtual environment')
    export_parser.add_argument('--output', type=str, default='requirements.txt', help='Path to the output requirements file')
    
    args = parser.parse_args()
    
    if args.command == 'create':
        success = create_environment(args.path, args.python)
    elif args.command == 'install':
        success = install_dependencies(args.requirements, args.packages, args.env)
    elif args.command == 'run':
        success = run_in_environment(args.command_args, args.env)
    elif args.command == 'export':
        success = export_requirements(args.env, args.output)
    else:
        parser.print_help()
        sys.exit(1)
    
    if not success:
        sys.exit(1)

if __name__ == '__main__':
    main() 