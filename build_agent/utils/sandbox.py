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


import docker
import pexpect
import time 
import subprocess
import os 
import glob
import re
import sys
import json
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from parser.parse_command import match_download, match_runpipreqs, match_runtest, match_poetryruntest, match_conflict_solve, match_waitinglist_add, match_waitinglist_addfile, match_conflictlist_clear, match_waitinglist_clear, match_waitinglist_show, match_conflictlist_show, match_clear_configuration, match_cargo_deps, match_maven_deps, match_gradle_deps, match_npm_deps, match_go_deps, match_npm_build, match_maven_build, match_gradle_build, match_cargo_build, match_go_build, match_cmake_build, match_jest_test, match_junit_test, match_cargo_test, match_go_test, match_change_python_version
from download import download
from outputcollector import OutputCollector
from show_msg import show_msg

# 这部分bash语句通常认为不会对于系统产生影响，如果下面safe_cmd打头，且不存在">"这样的重定向符，则不commit
safe_cmd = [
    "cd", "ls", "cat", "echo", "pwd", "whoami", "who", "date", "cal", "df", "du",
    "free", "uname", "uptime", "w", "ps", "pgrep", "top", "htop", "vmstat", "iostat",
    "dmesg", "tail", "head", "more", "less", "grep", "find", "locate", "whereis", "which",
    "file", "stat", "cmp", "diff", "md5sum", "sha256sum", "gzip", "gunzip", "bzip2", "bunzip2",
    "xz", "unxz", "sort", "uniq", "wc", "tr", "cut", "paste", "tee", "awk", "sed", "env", "printenv",
    "hostname", "ping", "traceroute", "ssh", "journalctl","lsblk", "blkid", "uptime",
    "lscpu", "lsusb", "lspci", "lsmod", "dmidecode", "ip", "ifconfig", "netstat", "ss", "route", "nmap",
    "strace", "ltrace", "time", "nice", "renice", "killall", "printf"
    ]

# 用来截断，传入result_message为字符串，command为运行指令，truncate为正常阈值，bar_truncate为保留疑似进度条数量
def truncate_msg(result_message, command, truncate=2000, bar_truncate=20):
    lines = result_message.splitlines()
    lines = [x for x in lines if len(x.strip()) > 0]
    # 用来存疑似进度条的行数
    bar_lines = list()
    for i in range(len(lines)):
        line = lines[i]
        if line.strip().startswith('\x1b[') or line.count('\x1b[') >= 2 or line.count('█') >= 2 or '━━━━━' in line:
            bar_lines.append(i)
    if len(bar_lines) > bar_truncate:
        for i in range(len(lines)):
            if i in bar_lines[:-bar_truncate]:
                lines[i] = ''
    lines = [x for x in lines if len(x) > 0]

    result_message = '\n'.join(lines)
    res = result_message
    # 处理过长文本
    if len(result_message) > truncate * 3:
        res = f"Running `{command}`...\nThe output is too long, so we've truncated it to show you the first and last 5000 characters.\n"
        res += (result_message[:truncate*3] + "\n...[Truncation]...\n" + result_message[-truncate*3:])
    elif len(result_message.split(' ')) > truncate:
        res = f"Running `{command}`...\nThe output is too long, so we've truncated it to show you the first and last 2500 words.\n"
        res += (' '.join(result_message.split(' ')[:truncate]) + "\n...[Truncation]...\n" + ' '.join(result_message.split(' ')[-truncate:]))
    
    return res

def delete_dangling_image():
    # 获取所有 dangling 镜像的 ID
    dangling_images = subprocess.check_output('docker images --filter "dangling=true" -q', shell=True).decode('utf-8').strip()
    # 如果有 dangling 镜像，则删除它们
    if dangling_images:
        subprocess.run(f'docker rmi {dangling_images} > /dev/null 2>&1', shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def compare_versions(version1, version2):
    # 分割版本号字符串
    parts1 = version1.split('.')
    parts2 = version2.split('.')

    # 将较短的版本号列表用零填充，使两者长度一致
    max_len = max(len(parts1), len(parts2))
    parts1.extend(['0'] * (max_len - len(parts1)))
    parts2.extend(['0'] * (max_len - len(parts2)))

    # 逐一比较版本号部分
    for part1, part2 in zip(parts1, parts2):
        part1 = int(part1)
        part2 = int(part2)

        # 比较两个部分
        if part1 > part2:
            return 1
        elif part1 < part2:
            return -1

    # 如果每个部分都相同，则版本号相等
    return 0

class Sandbox:
    # Supported languages and their file extensions
    LANGUAGE_EXTENSIONS = {
        'python': ['.py', '.pyw', 'requirements.txt', 'pyproject.toml', 'Pipfile'],
        'javascript': ['.js', '.jsx', '.ts', '.tsx', 'package.json', 'yarn.lock', 'pnpm-lock.yaml'],
        'java': ['.java', 'pom.xml', 'build.gradle', 'build.gradle.kts'],
        'go': ['.go', 'go.mod', 'go.sum', 'Gopkg.toml'],
        'ruby': ['.rb', 'Gemfile', 'Gemfile.lock'],
        'php': ['.php', 'composer.json', 'composer.lock'],
        'rust': ['.rs', 'Cargo.toml', 'Cargo.lock'],
        'csharp': ['.cs', '.csproj', '.sln'],
        'cpp': ['.cpp', '.hpp', '.cc', '.hh', 'CMakeLists.txt', 'conanfile.txt'],
        'c': ['.c', '.h', 'Makefile']
    }

    # Package manager commands for different languages
    PACKAGE_MANAGERS = {
        'python': {
            'poetry': {'install': 'poetry install', 'add': 'poetry add'},
            'pip': {'install': 'pip install -r requirements.txt', 'add': 'pip install'},
            'pipenv': {'install': 'pipenv install', 'add': 'pipenv install'}
        },
        'javascript': {
            'npm': {'install': 'npm install', 'add': 'npm install'},
            'yarn': {'install': 'yarn install', 'add': 'yarn add'},
            'pnpm': {'install': 'pnpm install', 'add': 'pnpm add'}
        },
        'java': {
            'maven': {'install': 'mvn install', 'add': 'mvn dependency:get -Dartifact='},
            'gradle': {'install': 'gradle build', 'add': 'gradle --refresh-dependencies'}
        },
        'go': {
            'go': {'install': 'go mod download', 'add': 'go get'},
            'dep': {'install': 'dep ensure', 'add': 'dep ensure -add'}
        },
        'ruby': {
            'bundler': {'install': 'bundle install', 'add': 'bundle add'}
        },
        'php': {
            'composer': {'install': 'composer install', 'add': 'composer require'}
        },
        'rust': {
            'cargo': {'install': 'cargo build', 'add': 'cargo add'}
        },
        'csharp': {
            'dotnet': {'install': 'dotnet restore', 'add': 'dotnet add package'}
        },
        'cpp': {
            'conan': {'install': 'conan install .', 'add': 'conan install'},
            'vcpkg': {'install': 'vcpkg install', 'add': 'vcpkg install'}
        }
    }

    def __init__(self, namespace, repo_full_name, root_path):
        self.namespace = namespace
        self.client = docker.from_env(timeout=600)
        self.container = None
        self.shell = None
        self.commands = list()
        self.full_name = repo_full_name
        self.root_path = root_path
        self.detected_languages = set()
        self.language_stats = {}  # Track language usage statistics
        self.language_managers = {}  # Store package managers for each detected language
        self.build_configs = {}  # Store build configurations for each language
    
    def generate_dockerfile(self):
        # Base universal Dockerfile content that supports multiple languages
        dockerfile_content = """FROM ubuntu:focal-20231211

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y curl npm git nano wget vim unzip sudo cgroup-tools iproute2 iptables \
autoconf gperf flex bison \
bc \
&& mkdir -p /workspace/download

# Python environment setup with package managers
RUN apt-get install -y python3-pip python3-dev
RUN pip3 install pytest pipdeptree
# Poetry installation
RUN curl -sSL https://install.python-poetry.org
ENV PATH="/root/.local/bin:$PATH"
# Pipenv installation
RUN pip3 install pipenv
# Conda installation (Detect architecture)
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then \
        wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh -O /workspace/download/miniconda.sh; \
    else \
        wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /workspace/download/miniconda.sh; \
    fi && \
    bash /workspace/download/miniconda.sh -b -p /opt/conda && \
    rm /workspace/download/miniconda.sh

ENV PATH="/opt/conda/bin:$PATH"
"""

        """
        # D
        RUN wget https://netcologne.dl.sourceforge.net/project/d-apt/files/d-apt.list -O /etc/apt/sources.list.d/d-apt.list \
            && apt-get update --allow-insecure-repositories -y \
            && apt-get -y --allow-unauthenticated install --reinstall d-apt-keyring \
            && apt-get update && apt-get install -y dmd-compiler dub

        # kotlin
        RUN curl -o /tmp/kotlin-compiler.zip -SL https://github.com/JetBrains/kotlin/releases/download/v2.0.0/kotlin-compiler-2.0.0.zip \
            && mkdir /usr/local/kotlin && unzip /tmp/kotlin-compiler.zip -d /usr/local/kotlin \
            && rm -f /tmp/kotlin-compiler.zip
        ENV PATH=/usr/local/kotlin/kotlinc/bin:$PATH

        # iverilog && verilog-eval (TODO: remove verilog-eval)
        RUN cd /workspace \
            && git clone https://github.com/steveicarus/iverilog.git && cd iverilog \
            && git checkout 01441687235135d1c12eeef920f75d97995da333 \
            && sh ./autoconf.sh && ./configure && make -j4 \
            && make install \
            && cd /workspace \
            && git clone https://github.com/NVlabs/verilog-eval \
            && cd verilog-eval && git checkout 4b9b16e92f1d9cc520afbfa3ecd5a2f20a350fd5 \
            && sed -i '79d;112d' ./verilog_eval/execution.py \
            && cd ../ && pip install -e verilog-eval

        # lean 4
        RUN curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh -s -- -y --default-toolchain leanprover/lean4:v4.10.0-rc2
        ENV PATH=/root/.elan/bin:$PATH

        # Racket
        RUN apt-get update --allow-insecure-repositories -y && apt-get install -y racket

        # Swift
        RUN curl -o /workspace/download/swift.tar.gz -SL https://download.swift.org/swift-5.10.1-release/ubuntu2004/swift-5.10.1-RELEASE/swift-5.10.1-RELEASE-ubuntu20.04.tar.gz \
            && cd /workspace/download \
            && tar zxf swift.tar.gz \
            && mkdir /usr/local/swift \
            && mv swift-5.10.1-RELEASE-ubuntu20.04/usr/* /usr/local/swift \
            && rm -f /workspace/download/swift.tar.gz
        ENV PATH=/usr/local/swift/bin:$PATH
        """

        dockerfile_path = f'{self.root_path}/utils/repo/{self.full_name}/Dockerfile'
        with open(dockerfile_path, "w") as f:
            f.write(dockerfile_content)
        return f'{self.root_path}/utils/repo/{self.full_name}'
    
    def build_image(self):
        dockerfile_path = self.generate_dockerfile()
        self.namespace = 'build_env_' + self.namespace

        try:
            # subprocess.run(["docker", "build", ".", "--no-cache", "-t", self.namespace], cwd=dockerfile_path, check=True)
            subprocess.run(["docker", "build", ".", "-t", self.namespace], cwd=dockerfile_path, check=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"Image build failed: {e}")
            return False
    
    def change_python_version(self, python_version):
        try:
            self.commit_container()
        except:
            pass
        self.namespace = f'python:{python_version}'
        try:
            self.start_container()
        except:
            self.switch_to_pre_image()
            return f'Change python version wrong! We have already rollback to the previous state. Please try another python version!\n{e}'
        return self
    
    # def change_base_image(self, base_image_name):
    #     try:
    #         self.commit_container()
    #     except:
    #         pass
    #     self.namespace = base_image_name.strip().lower()
    #     try:
    #         self.start_container()
    #     except Exception as e:
    #         self.switch_to_pre_image()
    #         return f'Change base image wrong! We have already rollback to the previous state. Please try another base image!\n{e}'
    #     return self


    def commit_container(self):
        try:
            delete_dangling_image()
            # 将容器提交成固定名称的镜像
            image = self.container.commit(repository=f"{self.full_name.lower().replace('/', '_').replace('-', '_')}", tag='tmp')
            # subprocess.run(f'docker commit {self.container.name} running_env:tmp', shell=True)
            # print(f"Container {self.container.name} committed as image running_env:tmp.")
            return True
        except docker.errors.ContainerError as e:
            print(f"Error committing container: {e}")
            return None

    def switch_to_pre_image(self):
        try:
            # tmp_image_name = "running_env:tmp"
            tmp_image_name = f"{self.full_name.lower().replace('/', '_').replace('-', '_')}:tmp"
            # print(f"Switching to tmp image: {tmp_image_name}")

            # 停止并移除现有的容器
            if self.container:
                self.container.stop()
                self.container.remove()
                delete_dangling_image()
            
            host_path = '/tmp/patch'
            container_path = '/tmp/patch'
            # 创建并启动一个新的容器，使用 tmp 镜像
            self.container = self.client.containers.run(
                tmp_image_name,
                detach=True,
                tty=True,
                stdin_open=True,
                volumes={host_path: {'bind': container_path, 'mode': 'rw'}},
                privileged=True,
                mem_limit='30g',
                network_mode='bridge',
                cpuset_cpus='0-1',
                )

            # 启动新的 shell 会话
            self.start_shell()
            return True
        
        except docker.errors.ImageNotFound as e:
            print(f"Image not found: {e}")
            return False
        except docker.errors.ContainerError as e:
            print(f"Error switching to tmp container: {e}")
            return False
        except Exception as generic_error:
            print(f"ls : {generic_error}")
            return False

    # 获取容器内的项目路径
    def get_project_path(self):
        project_path = self.container.exec_run("pwd").output.decode().strip()
        return project_path
    
    def detect_languages(self):
        """Enhanced language detection with usage statistics."""
        try:
            repo_path = f'{self.root_path}/utils/repo/{self.full_name}/repo'
            language_files = {lang: [] for lang in self.LANGUAGE_EXTENSIONS.keys()}
            
            for root, _, files in os.walk(repo_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    for lang, extensions in self.LANGUAGE_EXTENSIONS.items():
                        if any(file.endswith(ext) for ext in extensions):
                            self.detected_languages.add(lang)
                            language_files[lang].append(file_path)
                            
                            # Check for build and config files
                            if file in ['pyproject.toml', 'setup.py', 'requirements.txt'] or file.endswith('.py'):
                                self.build_configs['python'] = self.build_configs.get('python', file)
                            elif file in ['package.json', 'tsconfig.json'] or any(file.endswith(ext) for ext in ['.js', '.jsx', '.ts', '.tsx']):
                                self.build_configs['javascript'] = self.build_configs.get('javascript', file)
                            elif file in ['pom.xml', 'build.gradle'] or file.endswith('.java'):
                                self.build_configs['java'] = self.build_configs.get('java', file)
                            elif file == 'go.mod' or file.endswith('.go'):
                                self.build_configs['go'] = self.build_configs.get('go', file)
                            elif file == 'Cargo.toml' or file.endswith('.rs'):
                                self.build_configs['rust'] = self.build_configs.get('rust', file)
                            elif file == 'CMakeLists.txt' or any(file.endswith(ext) for ext in ['.cpp', '.hpp', '.cc', '.hh']):
                                self.build_configs['cpp'] = self.build_configs.get('cpp', file)
            
            # Calculate language statistics
            total_files = sum(len(files) for files in language_files.values())
            self.language_stats = {
                lang: {
                    'files': len(files),
                    'percentage': (len(files) / total_files * 100) if total_files > 0 else 0,
                    'config_files': [os.path.basename(f) for f in files if any(
                        f.endswith(conf) for conf in [
                            'requirements.txt', 'setup.py', 'pyproject.toml',  # Python
                            'package.json', 'tsconfig.json',                   # JavaScript
                            'pom.xml', 'build.gradle',                        # Java
                            'go.mod', 'Gopkg.toml',                          # Go
                            'Gemfile', 'Cargo.toml', 'composer.json'         # Others
                        ]
                    )]
                }
                for lang, files in language_files.items() if len(files) > 0
            }
            
            return self.detected_languages
        except Exception as e:
            print(f"Error detecting languages: {e}")
            return set()

    def setup_package_managers(self):
        """Set up package managers for all detected languages."""
        for lang in self.detected_languages:
            # Get default package manager for the language
            default_manager = {
                'python': 'pip',
                'javascript': 'npm',
                'java': 'maven',
                'go': 'go',
                'ruby': 'bundler',
                'php': 'composer',
                'rust': 'cargo',
                'csharp': 'dotnet',
                'cpp': 'conan'
            }.get(lang)
            
            # Check for language-specific config files
            config_files = {
                'pyproject.toml': ('python', 'poetry'),
                'Pipfile': ('python', 'pipenv'),
                'package-lock.json': ('javascript', 'npm'),
                'yarn.lock': ('javascript', 'yarn'),
                'pnpm-lock.yaml': ('javascript', 'pnpm'),
                'pom.xml': ('java', 'maven'),
                'build.gradle': ('java', 'gradle'),
                'Gopkg.toml': ('go', 'dep'),
                'Gemfile': ('ruby', 'bundler'),
                'composer.json': ('php', 'composer'),
                'Cargo.toml': ('rust', 'cargo'),
                'conanfile.txt': ('cpp', 'conan')
            }
            
            repo_path = f'{self.root_path}/utils/repo/{self.full_name}/repo'
            manager_set = False
            
            for config_file, (config_lang, manager) in config_files.items():
                if config_lang == lang and os.path.exists(os.path.join(repo_path, config_file)):
                    self.language_managers[lang] = manager
                    manager_set = True
                    break
            
            if not manager_set:
                self.language_managers[lang] = default_manager

    def install_all_dependencies(self):
        """Install dependencies for all detected languages."""
        results = {}
        for lang in self.detected_languages:
            if lang in self.language_managers:
                manager = self.language_managers[lang]
                try:
                    install_cmd = self.PACKAGE_MANAGERS[lang][manager]['install']
                    result = self.container.exec_run(f"cd /repo && {install_cmd}")
                    results[lang] = {
                        'success': result.exit_code == 0,
                        'output': result.output.decode('utf-8'),
                        'manager': manager
                    }
                except Exception as e:
                    results[lang] = {
                        'success': False,
                        'error': str(e),
                        'manager': manager
                    }
        return results

    def build_project(self):
        """Build the project for all detected languages."""
        build_results = {}
        
        # Language-specific build commands
        build_commands = {
            'python': {
                'poetry': 'poetry build',
                'pip': 'python setup.py build',
                'pipenv': 'pipenv run python setup.py build'
            },
            'javascript': {
                'npm': 'npm run build',
                'yarn': 'yarn build',
                'pnpm': 'pnpm build'
            },
            'java': {
                'maven': 'mvn package',
                'gradle': 'gradle build'
            },
            'go': {
                'go': 'go build ./...',
                'dep': 'dep ensure && go build ./...'
            },
            'rust': {
                'cargo': 'cargo build'
            },
            'cpp': {
                'cmake': 'cmake . && make',
                'conan': 'conan build .'
            }
        }
        
        for lang in self.detected_languages:
            if lang in self.language_managers and lang in build_commands:
                manager = self.language_managers[lang]
                if manager in build_commands[lang]:
                    try:
                        build_cmd = build_commands[lang][manager]
                        result = self.container.exec_run(f"cd /repo && {build_cmd}")
                        build_results[lang] = {
                            'success': result.exit_code == 0,
                            'output': result.output.decode('utf-8'),
                            'command': build_cmd
                        }
                    except Exception as e:
                        build_results[lang] = {
                            'success': False,
                            'error': str(e),
                            'command': build_cmd
                        }
        
        return build_results


    # 开启一个新的Container，返回1表示创建成功，返回-1表示创建失败
    def start_container(self, base_image=False):
        if not base_image:
            success = self.build_image()
            if success == 1:
                # Detect languages and set up package managers
                self.detect_languages()
                self.setup_package_managers()
                
                # Print language statistics
                print("\n=== Project Language Analysis ===")
                for lang, stats in self.language_stats.items():
                    if stats['files'] > 0:
                        print(f"\n{lang.upper()}:")
                        print(f"  Files: {stats['files']} ({stats['percentage']:.1f}%)")
                        if stats['config_files']:
                            print(f"  Config files: {', '.join(stats['config_files'])}")
                        print(f"  Package manager: {self.language_managers.get(lang, 'None')}")
            else:
                raise Exception('Build image error!')
        image = f"{self.namespace}"
        host_path = '/tmp/patch'
        container_path = '/tmp/patch'
        try:
            self.container = self.client.containers.run(
                image, 
                detach=True, 
                tty=True, 
                stdin_open=True, 
                privileged=True,
                volumes={host_path: {'bind': container_path, 'mode': 'rw'}}
                )

            print(f"\033[94mContainer {self.container.name} {self.container.short_id} started with image {image}\033[0m")
            
            current_file_path = os.path.abspath(__file__)
            current_directory = os.path.dirname(current_file_path)
            project_directory = os.path.dirname(current_directory)
            
            # Copy tools directory
            cmd = f"chmod -R 777 {project_directory}/tools && docker cp {project_directory}/tools {self.container.name}:/home"
            subprocess.run(cmd, check=True, shell=True)

            # Debug: Check source directory before copy
            print(f"\033[93mChecking source directory...\033[0m")
            source_path = f"{project_directory}/utils/repo/{self.full_name}/repo"
            ls_source = subprocess.run(f"ls -la {source_path}", shell=True, capture_output=True, text=True)
            print(f"\033[92mSource directory contents:\n{ls_source.stdout}\033[0m")

            # Copy repo directory
            print(f"\033[93mCopying repository to container...\033[0m")
            repo_cmd = f"docker cp {source_path} {self.container.name}:/"
            result = subprocess.run(repo_cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"\033[92mRepository copy successful!\033[0m")
            else:
                print(f"\033[91mRepository copy failed: {result.stderr}\033[0m")

            # Debug: Check destination directory after copy
            print(f"\033[93mVerifying /repo contents in container...\033[0m")
            ls_dest = subprocess.run(f"docker exec {self.container.name} ls -la /repo", shell=True, capture_output=True, text=True)
            print(f"\033[92mContainer /repo contents:\n{ls_dest.stdout}\033[0m")

            return 1
        except Exception as e:
            print(f"\033[91mContainer start failed: {e}\033[0m")
            return -1

    # 开启一个shell
    def start_shell(self):
        if self.container:
            if self.shell and self.shell.isalive():
                self.shell.close(force=True)  # 确保关闭之前的shell
            command = f'docker exec -it {self.container.id} /bin/bash'
            self.shell = pexpect.spawn(command)
            self.shell.expect([r'\$ ', r'# '], timeout=600)  # 等待bash提示符
        else:
            raise Exception("Container not started. Call start_container() first.")

    # 开启一个新的session
    def get_session(self):

        # 在获取session时启动新的shell
        self.start_shell()

        class Session:
            def __init__(self, sandbox):
                self.sandbox = sandbox
            
            def get_returncode(self):
                echo_returncode = '''echo $?'''
                self.sandbox.shell.sendline(echo_returncode)
                self.sandbox.shell.expect([r'root@.*:.*# '], timeout=600)
                # 获取 shell.before 中匹配到的模式之前的输出
                output = self.sandbox.shell.before.decode('utf-8').strip()
                output = output.replace('\x1b[?2004l\r', '')

                # 分析输出行，排除发送的命令行和最后的提示符行
                output_lines1 = output.split('\r\n')

                if len(output_lines1) > 1:
                    last_line = output_lines1[-1]
                    output_lines1 = output_lines1[1:-1]
                    id = last_line.find('''\x1b[''')
                    if id != -1 and len(last_line[:id].strip()) > 0:
                        output_lines1.append(last_line[:id].strip())
                return_code = '\n'.join(output_lines1).strip()
                return int(return_code)


            # 给download用的一个特殊函数
            def execute_simple(self, command, timeout=600):
                self.sandbox.commit_container()
                if command[-1] != '&':
                    start_time = time.time()
                    self.sandbox.commands.append({"command": command, "returncode": -2, "time": -1, "dir": '/'})
                    self.sandbox.shell.sendline(command + " && sleep 0.5")
                    self.sandbox.commands[-1]["returncode"] = -1
                else:
                    start_time = time.time()
                    self.sandbox.commands.append({"command": command, "returncode": -2, "time": -1, "dir": '/'})
                    self.sandbox.shell.sendline(command)
                    self.sandbox.commands[-1]["returncode"] = -1

                self.sandbox.shell.expect([r'root@.*:.*# '], timeout=600)  # 等待bash提示符，带超时
                end_time = time.time()
                elasped_time = end_time - start_time
                self.sandbox.commands[-1]["time"] = elasped_time

                # 获取 shell.before 中匹配到的模式之前的输出
                output = self.sandbox.shell.before.decode('utf-8').strip()
                output = output.replace('\x1b[?2004l\r', '')

                # 分析输出行，排除发送的命令行和最后的提示符行
                output_lines = output.split('\r\n')

                if len(output_lines) > 1:
                    last_line = output_lines[-1]
                    output_lines = output_lines[1:-1]
                    id = last_line.find('''\x1b[''')
                    if id != -1 and len(last_line[:id].strip()) > 0:
                        output_lines.append(last_line[:id].strip())
                res = '\n'.join(output_lines).strip()
                if len(res.split(' ')) > 5000:
                    res = "The output is too long, so we've truncated it to show you the first and last 2500 words."
                    res += (' '.join(res.split(' ')[:2500]) + '\n' + ' '.join(res.splitlines()[-2500:]))
                return_code = self.get_returncode()
                self.sandbox.commands[-1]['returncode'] = return_code
                if str(return_code) == '0':
                    return True, res
                else:
                    self.sandbox.switch_to_pre_image()
                    return False, res

            def execute(self, command, waiting_list, conflict_list, timeout=600):
                try:
                    if 'hatch shell' == command.lower().strip():
                        return 'You are not allowed to use commands like `hatch shell` that would open a new shell!!!', -1
                    # 在持久shell中执行命令
                    if '$pwd$' == command.lower().strip():
                        command = 'pwd'
                        self.sandbox.shell.sendline(command)
                        self.sandbox.shell.expect([r'root@.*:.*# '], timeout=600)  # 等待bash提示符，带超时
                        # 获取 shell.before 中匹配到的模式之前的输出
                        output = self.sandbox.shell.before.decode('utf-8').strip()
                        output = output.replace('\x1b[?2004l\r', '')
                        
                        # 分析输出行，排除发送的命令行和最后的提示符行
                        output_lines = output.split('\r\n')

                        if len(output_lines) > 1:
                            last_line = output_lines[-1]
                            output_lines = output_lines[1:-1]
                            id = last_line.find('''\x1b[''')
                            if id != -1 and len(last_line[:id].strip()) > 0:
                                output_lines.append(last_line[:id].strip())
                        return output_lines[0], 0
                    
                    if '$pip list --format json$' == command.lower().strip():
                        command = 'pip list --format json'
                        self.sandbox.shell.sendline(command)
                        self.sandbox.shell.expect([r'root@.*:.*# '], timeout=600)  # 等待bash提示符，带超时
                        # 获取 shell.before 中匹配到的模式之前的输出
                        output = self.sandbox.shell.before.decode('utf-8').strip()
                        output = output.replace('\x1b[?2004l\r', '')
                        
                        # 分析输出行，排除发送的命令行和最后的提示符行
                        output_lines = output.split('\r\n')

                        if len(output_lines) > 1:
                            last_line = output_lines[-1]
                            output_lines = output_lines[1:-1]
                            id = last_line.find('''\x1b[''')
                            if id != -1 and len(last_line[:id].strip()) > 0:
                                output_lines.append(last_line[:id].strip())
                        return output_lines[0], 0

                    if match_download(command):
                        with OutputCollector() as collector:
                            download(self, waiting_list, conflict_list)
                        result_message = f'Running `{command}`...\n' + collector.get_output() + '\n'
                        return truncate_msg(result_message, 'download'), 'unknown'
                    elif match_conflict_solve(command) != -1:
                        version_constraint = match_conflict_solve(command)['version_constraint']
                        unchanged = match_conflict_solve(command)['unchanged']
                        with OutputCollector() as collector:
                            conflict_list.solve(waiting_list, version_constraint, unchanged)
                        result_message = f'Running `{command}`...\n' + collector.get_output() + '\n'
                        return truncate_msg(result_message, command), 'unknown'
                    elif match_conflictlist_clear(command):
                        with OutputCollector() as collector:
                            conflict_list.clear()
                        result_message = f'Running `{command}`...\n' + collector.get_output() + '\n'
                        return truncate_msg(result_message, command), 'unknown'
                    elif match_waitinglist_add(command) != -1:
                        package_name = match_waitinglist_add(command)['package_name']
                        version_constraints = match_waitinglist_add(command)['version_constraints']
                        tool = match_waitinglist_add(command)['tool']
                        with OutputCollector() as collector:
                            waiting_list.add(package_name, version_constraints, tool, conflict_list)
                        result_message = f'Running `{command}`...\n' + collector.get_output() + '\n'
                        return truncate_msg(result_message, command), 'unknown'
                    elif match_waitinglist_addfile(command) != -1:
                        file_path = match_waitinglist_addfile(command)['file_path']
                        current_file_path = os.path.abspath(__file__)
                        current_directory = os.path.dirname(current_file_path)
                        project_directory = os.path.dirname(current_directory)
                        result = subprocess.run(f'docker cp {self.sandbox.container.name}:{file_path} {project_directory}/utils/repo/{self.sandbox.full_name}/repo', shell=True, capture_output=True)
                        if result.returncode != 0:
                            msg = f'\nRunning `{command}`...\n'
                            msg += f'The file {file_path} does not exist. Please ensure you have entered the correct absolute path, not a relative path! If you are unsure, you can use commands like `ls` to verify.'
                            return msg, 1
                        subprocess.run(f'sudo chown huruida:huruida {project_directory}/repo/{self.sandbox.full_name}/repo/{file_path.split("/")[-1]}', shell=True, capture_output=True)
                        with OutputCollector() as collector:
                            waiting_list.addfile(f'{project_directory}/utils/repo/{self.sandbox.full_name}/repo/{file_path.split("/")[-1]}', conflict_list)
                        result_message = f'Running `{command}`...\n' + collector.get_output() + '\n'
                        return truncate_msg(result_message, command), 'unknown'
                    elif match_waitinglist_clear(command):
                        with OutputCollector() as collector:
                            waiting_list.clear()
                        result_message = f'Running `{command}`...\n' + collector.get_output() + '\n'
                        return truncate_msg(result_message, command), 'unknown'
                    elif match_waitinglist_show(command):
                        with OutputCollector() as collector:
                            waiting_list.get_message()
                        result_message = f'Running `{command}`...\n' + collector.get_output() + '\n'
                        return truncate_msg(result_message, command), 'unknown'
                    elif match_conflictlist_show(command):
                        with OutputCollector() as collector:
                            conflict_list.get_message(waiting_list)
                        result_message = f'Running `{command}`...\n' + collector.get_output() + '\n'
                        return truncate_msg(result_message, command), 'unknown'
                    elif 'pytest' in command.lower() and 'pip' not in command.lower():
                        msg = 'Please do not use `pytest` directly, but use `runtest` or `poetryruntest`(When you configured in poetry environment) instead. If there are something wrong when running `runtest` or `poetryruntest`, please solve it and run it again!'
                        result_message = msg
                        return result_message, 1
                    elif command.split(' ')[0] == 'rm' and (command.split('/')[-1].startswith('test_') or command.split('/')[-1].endswith('_test.py')):
                        msg = 'Please do not directly delete the testing file to pass the test!'
                        result_message = msg
                        return result_message, 1
                    elif command.split(' ')[0] == 'mv' and (command.split('/')[-1].startswith('test_') or command.split('/')[-1].endswith('_test.py')):
                        msg = 'Please do not directly move the testing file to pass the test!'
                        result_message = msg
                        return result_message, 1
                    else:
                        if match_runtest(command):
                            command = 'python /home/tools/runtest.py'
                        if match_poetryruntest(command):
                            command = 'python /home/tools/poetryruntest.py'
                        if match_runpipreqs(command):
                            command = 'python /home/tools/runpipreqs.py'
                        if command == 'generate_diff':
                            command = 'python /home/tools/generate_diff.py'
                        if match_cargo_deps(command):
                            command = 'python /home/tools/cargo_deps.py'
                        if match_maven_deps(command):
                            command = 'python /home/tools/maven_deps.py'
                        if match_gradle_deps(command):
                            command = 'python /home/tools/gradle_deps.py'
                        if match_npm_deps(command):
                            command = 'python /home/tools/npm_deps.py'
                        if match_go_deps(command):
                            command = 'python /home/tools/go_deps.py'
                        if match_npm_build(command):
                            command = 'python /home/tools/npm_build.py'
                        if match_maven_build(command):
                            command = 'python /home/tools/maven_build.py'
                        if match_gradle_build(command):
                            command = 'python /home/tools/gradle_build.py'
                        if match_cargo_build(command):
                            command = 'python /home/tools/cargo_build.py'
                        if match_go_build(command):
                            command = 'python /home/tools/go_build.py'
                        if match_cmake_build(command):
                            command = 'python /home/tools/cmake_build.py'
                        if match_jest_test(command):
                            command = 'python /home/tools/jest_test.py'
                        if match_junit_test(command):
                            command = 'python /home/tools/junit_test.py'
                        if match_cargo_test(command):
                            command = 'python /home/tools/cargo_test.py'
                        if match_go_test(command):
                            command = 'python /home/tools/go_test.py'
                        if command[-1] != '&':
                            if not (command.split()[0].strip() in safe_cmd and '>' not in command):
                                self.sandbox.commit_container()
                            start_time = time.time()
                            dir, return_code = self.execute('$pwd$', waiting_list, conflict_list)
                            self.sandbox.commands.append({"command": command, "returncode": -2, "time": -1, "dir": dir})
                            self.sandbox.shell.sendline(command + " && sleep 0.5")
                            self.sandbox.commands[-1]["returncode"] = -1
                        else:
                            if not (command.split()[0].strip() in safe_cmd and '>' not in command):
                                self.sandbox.commit_container()
                            start_time = time.time()
                            dir, return_code = self.execute('$pwd$', waiting_list, conflict_list)
                            self.sandbox.commands.append({"command": command, "returncode": -2, "time": -1, "dir": dir})
                            self.sandbox.shell.sendline(command)
                            self.sandbox.commands[-1]["returncode"] = -1

                        self.sandbox.shell.expect([r'root@.*:.*# '], timeout=600*2)  # 等待bash提示符，带超时
                        end_time = time.time()
                        elasped_time = end_time - start_time
                        self.sandbox.commands[-1]["time"] = elasped_time

                        # 获取 shell.before 中匹配到的模式之前的输出
                        output = self.sandbox.shell.before.decode('utf-8').strip()
                        output = output.replace('\x1b[?2004l\r', '')

                        # 分析输出行，排除发送的命令行和最后的提示符行
                        output_lines = output.split('\r\n')

                        if len(output_lines) > 1:
                            last_line = output_lines[-1]
                            output_lines = output_lines[1:-1]
                            id = last_line.find('''\x1b[''')
                            if id != -1 and len(last_line[:id].strip()) > 0:
                                output_lines.append(last_line[:id].strip())
                        try:
                            return_code = self.get_returncode()
                        except:
                            return_code = 123
                        try:
                            self.sandbox.commands[-1]["returncode"] = return_code
                        except:
                            self.sandbox.commands[-1]["returncode"] = 111
                            self.sandbox.commands[-1]["error_msg"] = return_code

                        if return_code != 0 and not ((command == 'python /home/tools/runtest.py' or command == 'python /home/tools/poetryruntest.py') and return_code == 5):
                            if command.strip().lower().startswith('conflict'):
                                msg = '''conflictlist command usage error, the following command formats are legal:
1. `conflictlist solve`
Explanation: The standalone `conflictlist solve` command means not to impose any version constraints, i.e., to default to downloading the latest version of the third-party library. This will update the version constraint in the waiting list to be unrestricted.
2. `conflictlist solve -v "==2.0"`
Explanation: Adding -v followed by a version constraint enclosed in double quotes updates the version constraint in the waiting list to that specific range, such as "==2.0", meaning to take version 2.0.
3. `conflictlist solve -v ">3.0"`
Explanation: Similar to the command 2, this constraint specifies a version number greater than 3.0.
4. `conflictlist solve -u`
Explanation: Adding -u indicates giving up all the constraints in the conflict list while still retaining the constraints in the waiting list, i.e., not updating the constraints for that library in the waiting list.
5. `conflictlist clear`
Explanation: Clear all the items in the conflict list.'''
                                result_message = f'Running `{command}`...\n' + msg + '\n'
    
                                return result_message, return_code
                            elif command.strip().lower().startswith('waiting'):
                                msg = '''waitinglist command usage error, the following command formats are leagal:
1. `waitinglist add -p package_name1 -v >=1.0.0 -t pip`
Explanation: Add package_name1>=1.0.0 into waiting list(using pip), and version constraints string cannot contain spaces.
2. `waitinglist add -p package_name1 -t pip`
Explanation: Add package_name1 into waiting list, no `-v` means download the latest version by default.
3. `waitinglist addfile /path/to/file`
Explanation: Add all the items in the /path/to/file into waiting list. Note that you must make sure each line's item meet the formats like [package_name][version_constraints].
4. `waitinglist clear`
Explanation: Clear all the items in the waiting list.'''
                                result_message = f'Running `{command}`...\n' + msg + '\n'
    
                                return result_message, return_code
                            # 如果是会改变状态的指令执行错误，则回退
                            if not (command.split()[0].strip() in safe_cmd and '>' not in command):
                                self.sandbox.switch_to_pre_image()
                                output_lines.append('The command execution failed, so I have reverted it back to the previous state, which is the environment before running this command.')
                            else:
                                output_lines.append('The command execution failed, please carefully check the output!')
                        result_message = '\n'.join(output_lines)
                        if 'Congratulations, you have successfully configured the environment!' in result_message or command == 'python /home/tools/generate_diff.py'\
                            or command == 'pipdeptree --json-tree' or command == 'pipdeptree':
                            # Python dependencies
                            try:
                                pipdeptree_json, pipdeptree_json_return_code = self.execute('pipdeptree --json-tree', waiting_list, conflict_list)
                            except:
                                pipdeptree_json_return_code = -1
                            try:
                                pipdeptree_normal, pipdeptree_normal_return_code = self.execute('pipdeptree', waiting_list, conflict_list)
                            except:
                                pipdeptree_normal_return_code = -1
                            try:
                                generate_diff, generate_diff_return_code = self.execute('generate_diff', waiting_list, conflict_list)
                            except:
                                generate_diff_return_code = -1
                            try:
                                pip_list, pip_list_return_code = self.execute('$pip list --format json$', waiting_list, conflict_list)
                            except:
                                pip_list_return_code = -1

                            # Node.js dependencies
                            try:
                                npm_list, npm_list_return_code = self.execute('npm list --json', waiting_list, conflict_list)
                            except:
                                npm_list_return_code = -1
                            try:
                                yarn_list, yarn_list_return_code = self.execute('yarn list --json', waiting_list, conflict_list)
                            except:
                                yarn_list_return_code = -1

                            # Java dependencies
                            try:
                                mvn_deps, mvn_deps_return_code = self.execute('mvn dependency:tree -DoutputType=dot', waiting_list, conflict_list)
                            except:
                                mvn_deps_return_code = -1
                            try:
                                gradle_deps, gradle_deps_return_code = self.execute('gradle dependencies', waiting_list, conflict_list)
                            except:
                                gradle_deps_return_code = -1

                            # Rust dependencies
                            try:
                                cargo_deps, cargo_deps_return_code = self.execute('cargo tree --format=json', waiting_list, conflict_list)
                            except:
                                cargo_deps_return_code = -1

                            # Go dependencies
                            try:
                                go_list, go_list_return_code = self.execute('go list -m -json all', waiting_list, conflict_list)
                            except:
                                go_list_return_code = -1

                            # Save dependency information
                            output_dir = f'{self.sandbox.root_path}/output/{self.sandbox.full_name}'
                            os.makedirs(output_dir, exist_ok=True)
                            os.makedirs(f'{output_dir}/patch', exist_ok=True)

                            # Save Python dependencies
                            if len(generate_diff.strip()) > 0 and generate_diff_return_code == 0:
                                with open(f'{output_dir}/patch/final_patch.diff', 'w') as w0:
                                    w0.write(generate_diff)
                            if pipdeptree_json_return_code == 0:
                                with open(f'{output_dir}/pipdeptree.json', 'w') as w1:
                                    w1.write(pipdeptree_json)
                            if pipdeptree_normal_return_code == 0:
                                with open(f'{output_dir}/pipdeptree.txt', 'w') as w2:
                                    w2.write(pipdeptree_normal)
                            if pip_list_return_code == 0:
                                with open(f'{output_dir}/pip_list.json', 'w') as w2:
                                    w2.write(json.dumps(json.loads(pip_list), indent=4))

                            # Save Node.js dependencies
                            if npm_list_return_code == 0:
                                with open(f'{output_dir}/npm_list.json', 'w') as w:
                                    w.write(npm_list)
                            if yarn_list_return_code == 0:
                                with open(f'{output_dir}/yarn_list.json', 'w') as w:
                                    w.write(yarn_list)

                            # Save Java dependencies
                            if mvn_deps_return_code == 0:
                                with open(f'{output_dir}/maven_deps.dot', 'w') as w:
                                    w.write(mvn_deps)
                            if gradle_deps_return_code == 0:
                                with open(f'{output_dir}/gradle_deps.txt', 'w') as w:
                                    w.write(gradle_deps)

                            # Save Rust dependencies
                            if cargo_deps_return_code == 0:
                                with open(f'{output_dir}/cargo_deps.json', 'w') as w:
                                    w.write(cargo_deps)

                            # Save Go dependencies
                            if go_list_return_code == 0:
                                with open(f'{output_dir}/go_deps.json', 'w') as w:
                                    w.write(go_list)

                            return result_message, return_code
                
                except pexpect.TIMEOUT:
                    if match_runtest(command) or match_poetryruntest(command):
                        os.sytem(f'touch {self.sandbox.root_path}/output/{self.sandbox.full_name}/TIMEOUT')
                        sys.exit(123)
                    partial_output = self.sandbox.shell.before.decode('utf-8').strip()
                    partial_output_lines = partial_output.split('\n')
                    if len(partial_output_lines) > 1:
                        partial_output_lines = partial_output_lines[1:-1]
                    partial_output = '\n'.join(partial_output_lines)
                    return f"Error: Command '{command}' timed out after {timeout} seconds. Partial output:\n + {partial_output}", 1
                
                return result_message, return_code

            def edit(self, edit_tmp_file:str, project_path:str, file_path = None, start_line = 0, end_line = 0, timeout=600):
                if file_path:
                    if file_path.split('/')[-1].startswith('test_') or file_path('/')[-1].endswith('_test.py'):
                        msg = f'Running Edit...\n' + f'You are trying to modify file {file_path}, but we require that you should not modify the testing files. Please consider alternative solutions.' + '\n'
                        return msg, 1
                if not file_path:
                    command = f"python /home/tools/code_edit.py -t '{edit_tmp_file}' -p '{project_path}'"
                else:
                    command = f"python /home/tools/code_edit.py -t '{edit_tmp_file}' -p '{project_path}' -f '{file_path}' -s {start_line} -e {end_line}"
                try:
                    start_time = time.time()
                    self.sandbox.commands.append({"command": command, "returncode": -2, "time": -1, "dir": '/'})
                    # 在持久shell中执行命令
                    self.sandbox.shell.sendline(command)
                    end_time = time.time()
                    self.sandbox.commands[-1]["returncode"] = -1
                    elasped_time = end_time - start_time
                    self.sandbox.commands[-1]["time"] = elasped_time
                    self.sandbox.shell.expect([r'root@.*:.*# '], timeout=timeout)  # 等待bash提示符，带超时

                    # 获取 shell.before 中匹配到的模式之前的输出
                    output = self.sandbox.shell.before.decode('utf-8').strip()
                
                    # 分析输出行，排除发送的命令行和最后的提示符行
                    output_lines = output.split('\r\n')
                    if len(output_lines) > 1:
                        output_lines = output_lines[1:-1]  # 排除发送的命令行

                    result_message = f'Running Edit...\n' + '\n'.join(output_lines)
                    try:
                        return_code = self.get_returncode()
                    except:
                        return_code = 123
                    self.sandbox.commands[-1]['returncode'] = return_code
                    return result_message, return_code

                except pexpect.TIMEOUT:
                    return 'Running Edit...\n' + f"Error: Edit timed out after {timeout} seconds." + '\n', 1
                
            def close(self):
                if self.sandbox.shell:
                    self.sandbox.shell.sendline('exit')
                    self.sandbox.shell.expect(pexpect.EOF)
                    self.sandbox.shell.close(force=True)
                    self.sandbox.shell = None  # 设置shell为None

        return Session(self)

    def stop_container(self):
        if self.container:
            if self.shell and self.shell.isalive():
                self.shell.close(force=True)  # 确保关闭shell
                self.shell = None
            self.container.stop()
            self.container.remove()
            print(f"Container {self.container.short_id} stopped and removed")
            self.container = None
            subprocess.run(f"docker rmi {self.full_name.lower().replace('/', '_').replace('-', '_')}:tmp > /dev/null 2>&1", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return self.commands


if __name__ == "__main__":
    from conflict_list import ConflictList
    from waiting_list import WaitingList
    waiting_list = WaitingList()
    conflict_list = ConflictList()
    sandbox = Sandbox("python:3.10", "shower/shower", "/Users/tianyangliu/Projects/X-Repo2Run/build_agent")
    sandbox.start_container()
    session = sandbox.get_session()
    while True:
        a = input()
        result, return_code = session.execute(a, waiting_list, conflict_list)
        print('result:\n' + result)
        print('return_code:\n' + str(return_code))
    session.close()
    sandbox.stop_container()
