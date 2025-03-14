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


import argparse
import json
import multiprocessing
import threading
import time
import os
import sys
from datetime import datetime, timedelta
from utils.sandbox import Sandbox
from agents.configuration import Configuration
import subprocess
from utils.waiting_list import WaitingList
from utils.conflict_list import ConflictList
from utils.integrate_dockerfile import integrate_dockerfile
import ast
import shutil

def move_files_to_repo(source_folder):
    # Define target folder path
    target_folder = os.path.join(source_folder, 'repo_inner_directory_long_long_name_to_avoid_duplicate')
    
    # Create target folder if it doesn't exist
    if not os.path.exists(target_folder):
        os.mkdir(target_folder)
    
    # Move all files except the target folder
    for item in os.listdir(source_folder):
        item_path = os.path.join(source_folder, item)
        
        if item == 'repo_inner_directory_long_long_name_to_avoid_duplicate':
            continue
        
        shutil.move(item_path, os.path.join(target_folder, item))

    os.rename(target_folder, os.path.join(source_folder, 'repo'))

def setup_local_repo(root_path, local_path, author_name="local", repo_name="repo"):
    """Set up a local repository for processing"""
    target_dir = f'{root_path}/utils/repo/{author_name}/{repo_name}'
    
    # Create target directory structure
    os.makedirs(target_dir, exist_ok=True)
    
    # Copy local files to target location
    shutil.copytree(local_path, target_dir, dirs_exist_ok=True)
    
    # Move files to repo subdirectory consistently with remote repos
    move_files_to_repo(target_dir)
    
    # Create .pipreqs directory and generate requirements if possible
    os.makedirs(f'{target_dir}/repo/.pipreqs', exist_ok=True)
    pipreqs_cmd = "pipreqs --savepath=.pipreqs/requirements_pipreqs.txt --force"
    try:
        pipreqs_result = subprocess.run(pipreqs_cmd, cwd=f"{target_dir}/repo", 
                                      capture_output=True, shell=True)
        with open(f'{target_dir}/repo/.pipreqs/pipreqs_output.txt', 'w') as w1:
            w1.write(pipreqs_result.stdout.decode('utf-8'))
        with open(f'{target_dir}/repo/.pipreqs/pipreqs_error.txt', 'w') as w2:
            w2.write(pipreqs_result.stderr.decode('utf-8'))
    except:
        pass

    # Create output directory
    os.makedirs(f'{root_path}/output/{author_name}/{repo_name}', exist_ok=True)
    with open(f'{root_path}/output/{author_name}/{repo_name}/sha.txt', 'w') as w1:
        w1.write('local')

def download_repo(root_path, full_name, sha):
    if len(full_name.split('/')) != 2:
        raise Exception("full_name Wrong!!!")
    author_name = full_name.split('/')[0]
    repo_name = full_name.split('/')[1]
    
    # Create or clean the author directory
    author_dir = f'{root_path}/utils/repo/{author_name}'
    os.makedirs(author_dir, exist_ok=True)
    
    # Remove existing repo directory if it exists
    repo_dir = f'{author_dir}/{repo_name}'
    if os.path.exists(repo_dir):
        shutil.rmtree(repo_dir)
    
    # Clone the repository
    download_cmd = f"git clone https://github.com/{full_name}.git"
    subprocess.run(download_cmd, cwd=author_dir, check=True, shell=True)
    move_files_to_repo(f'{root_path}/utils/repo/{author_name}/{repo_name}')
    if os.path.exists(f"{root_path}/utils/repo/{author_name}/{repo_name}/repo/Dockerfile") and not os.path.isdir(f"{root_path}/utils/repo/{author_name}/{repo_name}/repo/Dockerfile"):
        rm_dockerfile_cmd = f"rm -rf {root_path}/utils/repo/{author_name}/{repo_name}/repo/Dockerfile"
        subprocess.run(rm_dockerfile_cmd, check=True, shell=True)
    pipreqs_cmd = "pipreqs --savepath=.pipreqs/requirements_pipreqs.txt --force"
    os.system(f'mkdir {root_path}/utils/repo/{author_name}/{repo_name}/repo/.pipreqs')
    try:
        pipreqs_warnings = subprocess.run(pipreqs_cmd, cwd=f"{root_path}/utils/repo/{author_name}/{repo_name}/repo", check=True, shell=True, capture_output=True)
        with open(f'{root_path}/utils/repo/{author_name}/{repo_name}/repo/.pipreqs/pipreqs_output.txt', 'w') as w1:
            w1.write(pipreqs_warnings.stdout.decode('utf-8'))
        with open(f'{root_path}/utils/repo/{author_name}/{repo_name}/repo/.pipreqs/pipreqs_error.txt', 'w') as w2:
            w2.write(pipreqs_warnings.stderr.decode('utf-8'))
    except:
        pass

    checkout_cmd = f"git checkout {sha}"
    subprocess.run(checkout_cmd, cwd=f'{root_path}/utils/repo/{author_name}/{repo_name}/repo', capture_output=True, shell=True)

    # x = subprocess.run('git log -1 --format="%H"', cwd=f'{root_path}/utils/repo/{author_name}/{repo_name}/repo', capture_output=True, shell=True)
    with open(f'{root_path}/utils/repo/{author_name}/{repo_name}/sha.txt', 'w') as w1:
        w1.write(sha)

def main():
    parser = argparse.ArgumentParser(description='Run script with either repository information or local path.')
    
    # Create mutually exclusive argument group
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument('--repo', nargs=2, metavar=('FULL_NAME', 'SHA'),
                            help='The full name of the repository (e.g., user/repo) and SHA')
    source_group.add_argument('--local', type=str, metavar='PATH',
                            help='Local folder path to process')
    
    parser.add_argument('--root_path', type=str, default='build_agent',
                       help='root path (optional, defaults to build_agent)')
    
    args = parser.parse_args()

    waiting_list = WaitingList()
    conflict_list = ConflictList()

    root_path = args.root_path
    if not os.path.isabs(root_path):
        root_path = os.path.abspath(root_path)

    if args.repo:
        full_name, sha = args.repo
        if len(full_name.split('/')) != 2:
            raise Exception("Repository full name must be in format 'user/repo'")
        download_repo(root_path, full_name, sha)
        author_name, repo_name = full_name.split('/')
    else:
        local_path = os.path.abspath(args.local)
        if not os.path.exists(local_path):
            raise Exception(f"Local path '{local_path}' does not exist")
        setup_local_repo(root_path, local_path)
        author_name, repo_name = "local", "repo"

    print(f"Processing {'repository: ' + author_name + '/' + repo_name if args.repo else 'local path: ' + args.local}")

    # Setup paths and directories
    repo_path = f"{author_name}/{repo_name}"
    output_path = f'{root_path}/output/{author_name}/{repo_name}'
    
    # Create or clean output directory
    if os.path.exists(f'{output_path}/patch'):
        rm_cmd = f"rm -rf {output_path}/patch"
        subprocess.run(rm_cmd, shell=True, check=True)
    if not os.path.exists(output_path):
        subprocess.run(f'mkdir -p {output_path}', shell=True)

    # Setup or clean repo directory
    repo_dir = f'{root_path}/utils/repo/{repo_path}'
    if os.path.exists(repo_dir):
        init_cmd = f"rm -rf {repo_dir} && mkdir -p {repo_dir}"
    else:
        init_cmd = f"mkdir -p {repo_dir}"
    subprocess.run(init_cmd, check=True, shell=True)
    
    def timer():
        time.sleep(3600*2)  # Wait for 2h
        print("Timeout for 2 hour!")
        os._exit(1)  # Force exit program

    # Start timer thread
    timer_thread = threading.Thread(target=timer)
    timer_thread.daemon = True
    timer_thread.start()

    # Setup repository (either download or copy local)
    if args.repo:
        download_repo(root_path, args.repo[0], args.repo[1])

    trajectory = []

    configuration_sandbox = Sandbox("python:3.10", repo_path, root_path)
    configuration_sandbox.start_container()
    configuration_agent = Configuration(configuration_sandbox, 'ubuntu', repo_path, root_path, 100)
    msg, outer_commands = configuration_agent.run('/tmp', trajectory, waiting_list, conflict_list)
    
    # Save outputs
    with open(f'{output_path}/track.json', 'w') as w1:
        w1.write(json.dumps(msg, indent=4))
    commands = configuration_sandbox.stop_container()
    with open(f'{output_path}/inner_commands.json', 'w') as w2:
        w2.write(json.dumps(commands, indent=4))
    with open(f'{output_path}/outer_commands.json', 'w') as w3:
        w3.write(json.dumps(outer_commands, indent=4))
    
    try:
        integrate_dockerfile(f'{output_path}')
        msg = f'Generate success!'
        with open(f'{output_path}/track.txt', 'a') as a1:
            a1.write(msg + '\n')
    except Exception as e:
        msg = f'integrate_docker failed, reason:\n {e}'
        with open(f'{output_path}/track.txt', 'a') as a1:
            a1.write(msg + '\n')

if __name__ == '__main__':
    try:
        subprocess.run('docker rmi $(docker images --filter "dangling=true" -q) > /dev/null 2>&1', shell=True)
    except:
        print("No dangling images")
    start_time = time.time()
    main()
    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f'Spend totally {elapsed_time}.')