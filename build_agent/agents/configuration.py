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

import os, sys, json
import subprocess
from agents.agent import Agent
from utils.llm import get_llm_response
from utils.agent_util import safe_cmd, extract_commands, append_trajectory, TIME_OUT_LABEL, extract_diffs, save_diff_description, DIFF_FENCE, BASH_FENCE, INIT_PROMPT, EDIT_PROMPT, HEAD, DIVIDER, UPDATED
from utils.tools_config import Tools
from utils.split_cmd import split_cmd_statements
import re
import time

def res_truncate(text):
    keywords = ['''waitinglist command usage error, the following command formats are leagal:
1. `waitinglist add -p package_name1 -v >=1.0.0 -t pip`
Explanation: Add package_name1>=1.0.0 into waiting list(using pip), and version constraints string cannot contain spaces.
2. `waitinglist add -p package_name1 -t pip`
Explanation: Add package_name1 into waiting list, no `-v` means download the latest version by default.
3. `waitinglist addfile /path/to/file`
Explanation: Add all the items in the /path/to/file into waiting list. Note that you must make sure each line's item meet the formats like [package_name][version_constraints].
4. `waitinglist clear`
Explanation: Clear all the items in the waiting list.''', 
        'If you have multiple elements to add to the waitinglist, you can use && to connect multiple `waitinglist add` statements and surround them with ```bash and ```. Please make sure to write the complete statements; we will only recognize complete statements. Do not use ellipses or other incomplete forms.',
        '''conflictlist command usage error, the following command formats are legal:
1. `conflictlist solve`
Explanation: The standalone `conflictlist solve` command means not to impose any version constraints, i.e., to default to downloading the latest version of the third-party library. This will update the version constraint in the waiting list to be unrestricted.
2. `conflictlist solve -v "==2.0"`
Explanation: Adding -v followed by a version constraint enclosed in double quotes updates the version constraint in the waiting list to that specific range, such as "==2.0", meaning to take version 2.0.
3. `conflictlist solve -v ">3.0"`
Explanation: Similar to the command 2, this constraint specifies a version number greater than 3.0.
4. `conflictlist solve -u`
Explanation: Adding -u indicates giving up all the constraints in the conflict list while still retaining the constraints in the waiting list, i.e., not updating the constraints for that library in the waiting list.
5. `conflictlist clear`
Explanation: Clear all the items in the conflict list.''',
        'If you have multiple elements to remove from the conflict list, you can use && to connect multiple `conflictlist solve` statements and surround them with ```bash and ```. Please make sure to write the complete statements; we will only recognize complete statements. Do not use ellipses or other incomplete forms.'
        ]
    # 遍历每个关键词，找到其在文本中出现的位置
    all_positions = {}
    for keyword in keywords:
        positions = [i for i in range(len(text)) if text.startswith(keyword, i)]
        if len(positions) > 1:
            all_positions[keyword] = positions

    if not all_positions:
        return text

    # 从结果文本开始，处理每个关键词的位置，保留最后一个
    new_text = text
    keywords_to_remove = sorted(all_positions.items(), key=lambda item: item[1][-1], reverse=True)

    for keyword, positions in keywords_to_remove:
        last_position = positions[-1]
        before_last_position = new_text[:last_position].replace(keyword, "", len(positions) - 1)
        after_last_position = new_text[last_position:]
        new_text = before_last_position + after_last_position

    return new_text

class Configuration(Agent):
    def __init__(self, sandbox, image_name, full_name, root_dir, max_turn=70):
        self.model = "gpt-4o-2024-05-13"
        # self.model = "aws_claude35_sonnet"
        self.root_dir = root_dir
        self.max_turn = max_turn
        self.sandbox = sandbox
        self.sandbox_session = self.sandbox.get_session()
        self.full_name = full_name
        self.detected_languages = set()  # Initialize detected_languages as an empty set
        self.tool_lib = [
            Tools.waiting_list_add,
            Tools.waiting_list_add_file,
            Tools.waiting_list_clear,
            Tools.conflict_solve_constraints,
            Tools.conflict_solve_u,
            Tools.conflict_clear,
            Tools.conflict_list_show,
            Tools.waiting_list_show,
            Tools.download,
            Tools.runtest,
            Tools.poetryruntest,
            Tools.runpipreqs,
            Tools.change_python_version,
            Tools.clear_configuration,
            Tools.npm_deps,
            Tools.maven_deps,
            Tools.gradle_deps,
            Tools.cargo_deps,
            Tools.go_deps,
            Tools.npm_build,
            Tools.maven_build,
            Tools.gradle_build,
            Tools.cargo_build,
            Tools.go_build,
            Tools.cmake_build,
            Tools.jest_test,
            Tools.junit_test,
            Tools.cargo_test,
            Tools.go_test,
            Tools.dotnet_test,
        ]
        self.image_name = image_name
        self.outer_commands = list()
        tools_list = ""
        for tool in self.tool_lib:
            tools_list += f"{tool.value['command']} # {tool.value['description']}\n"
        self.init_prompt = f"""\
You are an expert skilled in multi-language environment configuration. You can analyze various configuration files and structures in repositories to set up the appropriate development environment for different programming languages. Your goal is to ensure the repository can be successfully configured and able to correctly execute the specified tests.

WORK PROCESS:
1. **Project Analysis and Language Detection**:
   - Analyze repository structure to identify all programming languages in use
   - Check for language-specific configuration files:
     * Python: setup.py, requirements.txt, pyproject.toml, Pipfile
     * Node.js: package.json, yarn.lock, pnpm-lock.yaml
     * Java: pom.xml, build.gradle, settings.gradle
     * Go: go.mod, go.sum
     * Rust: Cargo.toml, Cargo.lock
     * C/C++: CMakeLists.txt, Makefile
     * C#: .csproj, .sln files
   - Determine primary and secondary languages if multi-language project
   - Map dependencies between different language components

2. **Environment Version Setup**:
   - For each detected language:
     a. Python: Use `change_python_version` if needed
     b. Node.js: Check .nvmrc or package.json engines field
     c. Java: Verify JDK version in pom.xml/build.gradle
     d. Go: Check go.mod for Go version
     e. Rust: Check rust-toolchain.toml or Cargo.toml
     f. C/C++: Check compiler version requirements
     g. C#: Check .NET SDK version requirements

3. **Dependency Analysis and Resolution**:
   For each detected language:
   a. Python:
      - Use `runpipreqs` for automatic dependency detection
      - Check setup.py, requirements.txt, pyproject.toml
      - Use `pipdeptree` for dependency tree analysis
   b. Node.js:
      - Use `npm_deps` to analyze package.json
      - Check for workspace configurations
   c. Java:
      - Use `maven_deps` or `gradle_deps`
      - Check for parent POMs and multi-module setups
   d. Go:
      - Use `go_deps` to analyze module dependencies
      - Check for workspace and replace directives
   e. Rust:
      - Use `cargo_deps` to analyze crate dependencies
      - Check for workspace members
   f. C/C++:
      - Analyze CMake dependencies
      - Check for conanfile.txt or vcpkg.json
   g. C#:
      - Analyze NuGet package references
      - Check for solution-level dependencies

4. **Build Configuration**:
   For each language:
   a. Python:
      - Configure poetry, pip, or pipenv
      - Set up editable installs for development
   b. Node.js:
      - Use `npm_build` to configure and build
      - Set up TypeScript compilation if needed
   c. Java:
      - Use `maven_build` or `gradle_build`
      - Configure resource filtering and profiles
   d. Go:
      - Use `go_build` with appropriate tags
      - Configure CGO if needed
   e. Rust:
      - Use `cargo_build` with appropriate features
      - Set up cross-compilation if needed
   f. C/C++:
      - Use `cmake_build` with appropriate options
      - Configure compiler flags
   g. C#:
      - Configure MSBuild properties
      - Set up assembly references

5. **Test Environment Setup**:
   Configure test runners for each language:
   - Python: pytest via `runtest` or `poetryruntest`
   - Node.js: Jest via `jest_test`
   - Java: JUnit via `junit_test`
   - Go: Go test via `go_test`
   - Rust: Cargo test via `cargo_test`
   - C#: xUnit/NUnit via `dotnet_test`

6. **Cross-Language Integration**:
   - Set up inter-language communication paths
   - Configure shared resources and assets
   - Set up environment variables for cross-language dependencies
   - Handle FFI/native dependencies
   - Verify language interop configurations

7. **Dependency Installation and Conflict Resolution**:
   For each language:
   a. Add dependencies to waiting list:
      - Python: `waitinglist addfile` for requirements.txt
      - Node.js: Use npm_deps for package.json
      - Java: Use maven_deps/gradle_deps
      - Others: Use respective dependency tools
   b. Resolve conflicts:
      - Use `conflictlist show` to view conflicts
      - Use `conflictlist solve` with appropriate version constraints
      - Handle cross-language dependency conflicts

8. **Build and Verify**:
   For each language:
   a. Build the project:
      - Python: pip install or poetry install
      - Node.js: Use `npm_build`
      - Java: Use `maven_build` or `gradle_build`
      - Go: Use `go_build`
      - Rust: Use `cargo_build`
      - C/C++: Use `cmake_build`
   b. Run tests:
      - Use language-specific test runners
      - Handle test dependencies
      - Set up test environment variables

9. **Error Handling and Debugging**:
   For each language:
   a. Dependency errors:
      - Use language-specific package managers
      - Check version compatibility
      - Resolve circular dependencies
   b. Build errors:
      - Check compiler/interpreter versions
      - Verify platform compatibility
      - Handle missing dependencies
   c. Test failures:
      - Analyze test requirements
      - Check environment variables
      - Debug test configurations

10. **Environment Validation**:
    - Verify all language runtimes are properly configured
    - Confirm all dependencies are correctly installed
    - Check cross-language integration points
    - Validate test environment setup
    - Ensure build artifacts are properly generated

Remember:
- You can run tests at any point using language-specific test runners
- Use `-q` flag when available to reduce output noise
- Prefer environment variables over file modifications
- Do not modify test files
- Handle cross-language dependencies carefully
- Consider build order in multi-language projects

AVAILABLE TOOLS:
{tools_list}

IMPORTANT NOTES:
- The environment supports multiple programming languages simultaneously
- Each language may have its own package manager and build tools
- Cross-language dependencies must be handled carefully
- Test configurations should be language-appropriate
- Do not modify test files
- Use language-specific test runners when available
- Handle version conflicts across languages
- Consider build order in multi-language projects
- Use quiet mode (-q) when available for package managers
- Avoid modifying source files unless absolutely necessary
- Do not delete test files
- Do not use commands that would open a new shell

You are now in the Docker environment of {self.image_name}. The environment supports multiple programming languages including Python, Node.js, Java, Go, Rust, C/C++, and others.

If you encounter import errors such as ModuleNotFoundError or ImportError, you can consider two solutions. One solution is to use external tools like pip or apt-get to download these dependencies. The other solution is to check for local dependencies in the repository; if local dependencies are available, you can use `export PYTHONPATH=` statements to set environment variables (preferably), or modify the __init__.py file to resolve the issue.
Please note that when manually using pip, apt-get, poetry, or other tools to download third-party libraries, try to use the `-q` (quiet) mode if available to reduce intermediate progress bar outputs. Additionally, we will help remove more obvious progress bar information to minimize interference with the analysis.
If you need to install packages using pip, please consider adding them to the waiting list first, and then use the `download` command to proceed with the installation.
In each round of the conversation, we will inform you of the commands that have been correctly executed and have changed the state of the current Docker container. Please reflect on each round's Observation in relation to the current state of the Docker container and decide the subsequent Action.
If you need to run two or more commands, please strictly follow the order by enclosing each command in ONE {BASH_FENCE[0]} and {BASH_FENCE[1]} blocks connected by "&&" with ONE line! It is not recommended to use backslashes (\) for line continuation. If you need to execute commands that span multiple lines, it is advisable to write them into a .sh file and then run the executable file. For example, if you want to enter the /repo directory and execute `poetry install`, you should input:
{BASH_FENCE[0]}
cd /repo && poetry install
{BASH_FENCE[1]}

For example in the case of Python, it is not recommended to directly input:
{BASH_FENCE[0]}
cd /repo
{BASH_FENCE[1]}
{BASH_FENCE[0]}
poetry install
{BASH_FENCE[1]}

Nor is it recommended to input:
{BASH_FENCE[0]}
cd /repo \\
poetry install
{BASH_FENCE[1]}

We also strongly request that you try to write the instructions on the same line as much as possible, and do not break them into multiple lines, as this may cause parsing errors. Even if the line of instructions contains a lot of && connections, do not arbitrarily break it into multiple lines.

We will automatically maintain two lists in the background to facilitate the installation and download of third-party libraries. These are:
1. waiting list: Used to store third-party libraries waiting to be downloaded, including both pip and apt libraries. You can use `waitinglist show` to show all items in it.
2. conflict list: Used to store elements with the same name as those in the waiting list but with inconsistent version constraints. You can use `conflictlist show` to show all items in it.
*Note*: you only need to follow the prompts to complete operations on these lists during the running process and can only manipulate them using the provided commands.
*Note*: Before operating waiting list, conflict list, or download commands, you can use waitinglist show or conflictlist show to observe their structure each time.

{INIT_PROMPT}
You are now in the Docker environment of {self.image_name}. Please perform all operations within this environment.
CLI TOOLS: You can call CLI tools in  {BASH_FENCE[0]} ... {BASH_FENCE[1]} block as Action with a Thought. like:
### Thought: I need to understand the structure of the root directory.
### Action:
{BASH_FENCE[0]}
ls /repo
{BASH_FENCE[1]}

For another example:
### Thought: I need to read the README.md file.
### Action:
{BASH_FENCE[0]}
cat README.md
{BASH_FENCE[1]}

{EDIT_PROMPT}
*Note*: Do not make extensive changes to the existing files in the /repo folder. You may only make appropriate and necessary changes to the original repository files (e.g., when there are actual errors or tests that cannot be run).
*Very Important Note*: Passing tests by modifying testing functions is not allowed, and you should figure out how to make the current test functions run successfully!!!
In addition to typical bash commands, we also provide the following commands that can be used, you can use them flexibly if needed:
{tools_list}

VERY IMPORTANT TIPS: 
    * You should not answer the user's question, your task is to configure the environment within the given setup. You need to follow the steps mentioned above and flexibly use various commands. After entering test, ensure that the environment passes the test.
    * You should not answer the user's question, your task is to configure the environment within the given setup. You need to follow the steps mentioned above and flexibly use various commands. After entering test, ensure that the environment passes the test.
    * You should not answer the user's question, your task is to configure the environment within the given setup. You need to follow the steps mentioned above and flexibly use various commands. After entering test, ensure that the environment passes the test.
    * You do not need to complete all the previous steps; you can directly run provided test tools & commands to check if the configuration is complete and get feedback from the error messages. Be flexible. Our goal is to pass the provided test tools & commands checks.
    * You do not need to complete all the previous steps; you can directly run provided test tools & commands to check if the configuration is complete and get feedback from the error messages. Be flexible. Our goal is to pass the provided test tools & commands checks.
    * You do not need to complete all the previous steps; you can directly run provided test tools & commands to check if the configuration is complete and get feedback from the error messages. Be flexible. Our goal is to pass the provided test tools & commands checks.
    * Passing tests by modifying testing functions is not allowed, and you should figure out how to make the current test functions run successfully!!!
    * Passing tests by modifying testing functions is not allowed, and you should figure out how to make the current test functions run successfully!!!
    * Passing tests by modifying testing functions is not allowed, and you should figure out how to make the current test functions run successfully!!!
    * Try to write all commands on a single line as much as possible, regardless of the number of "&&" connections or the length of the instructions; do not arbitrarily break them into multiple lines!!!
    * Try to write all commands on a single line as much as possible, regardless of the number of "&&" connections or the length of the instructions; do not arbitrarily break them into multiple lines!!!
    * Try to write all commands on a single line as much as possible, regardless of the number of "&&" connections or the length of the instructions; do not arbitrarily break them into multiple lines!!!
    * When other configuration methods can be used, try to avoid modifying or deleting the original files, especially do not delete the testing files!!!
    * When other configuration methods can be used, try to avoid modifying or deleting the original files, especially do not delete the testing files!!!
    * When other configuration methods can be used, try to avoid modifying or deleting the original files, especially do not delete the testing files!!!
    * You are not allowed to use commands like `hatch shell` that would open a new shell!!!
    * You are not allowed to use commands like `hatch shell` that would open a new shell!!!
    * You are not allowed to use commands like `hatch shell` that would open a new shell!!!
"""
    def show_init_prompt(self):
        print(self.init_prompt)
    
    def get_max_turn(self):
        return self.max_turn

    def _get_language_specific_info(self):
        """Get language-specific dependency and test information"""
        info = {}
        
        # Define language-specific dependency commands
        dependency_commands = {
            'python': [
                ('pipdeptree', 'pipdeptree --json-tree'),
                ('pip_list', '$pip list --format json$'),
                ('poetry', 'poetry show --tree --json') # Add poetry support
            ],
            'node': [
                ('npm_list', 'npm list --json'),
                ('yarn_list', 'yarn list --json'),  # Add yarn support
                ('pnpm_list', 'pnpm list --json')   # Add pnpm support
            ],
            'java': [
                ('maven_deps', 'mvn dependency:tree -DoutputType=json'),
                ('gradle_deps', 'gradle dependencies --console=plain') # Add gradle support
            ],
            'go': [
                ('go_list', 'go list -m all -json'),
                ('go_mod', 'go mod graph')
            ],
            'rust': [
                ('cargo_metadata', 'cargo metadata --format-version=1'),
                ('cargo_tree', 'cargo tree --format=json')
            ],
            'cpp': [
                ('cmake_deps', 'cmake --trace-expand'), # For CMake projects
                ('conan_deps', 'conan info .'),        # For Conan package manager
            ],
            'csharp': [
                ('nuget_deps', 'dotnet list package --format json')
            ]
        }

        for lang, commands in dependency_commands.items():
            if lang in self.detected_languages:
                info[lang] = {'deps': {}}
                for tool_name, command in commands:
                    try:
                        output, return_code = self.sandbox_session.execute(command, [], [])
                        if return_code == 0:
                            info[lang]['deps'][tool_name] = output
                    except Exception as e:
                        print(f"Error getting {lang} dependency info from {tool_name}: {e}")
                        continue

        # Add build system detection
        build_files = {
            'python': ['setup.py', 'pyproject.toml', 'requirements.txt', 'Pipfile'],
            'node': ['package.json', 'yarn.lock', 'pnpm-lock.yaml'],
            'java': ['pom.xml', 'build.gradle', 'build.gradle.kts'],
            'go': ['go.mod', 'go.work'],
            'rust': ['Cargo.toml'],
            'cpp': ['CMakeLists.txt', 'conanfile.txt', 'vcpkg.json'],
            'csharp': ['*.csproj', '*.sln']
        }

        # Add version information
        version_commands = {
            'python': 'python --version',
            'node': 'node --version',
            'java': 'java -version',
            'go': 'go version',
            'rust': 'rustc --version',
            'cpp': ['gcc --version', 'clang --version'],
            'csharp': 'dotnet --version'
        }

        # Collect version information
        for lang, command in version_commands.items():
            if lang in self.detected_languages:
                try:
                    if isinstance(command, list):
                        for cmd in command:
                            output, return_code = self.sandbox_session.execute(cmd, [], [])
                            if return_code == 0:
                                info[lang]['version'] = output
                                break
                    else:
                        output, return_code = self.sandbox_session.execute(command, [], [])
                        if return_code == 0:
                            info[lang]['version'] = output
                except Exception as e:
                    print(f"Error getting {lang} version: {e}")

        return info

    def _is_test_file(self, filename):
        """Check if file is a test file across different languages"""
        test_patterns = {
            'python': [r'^test_.*\.py$', r'.*_test\.py$'],
            'node': [r'.*\.test\.js$', r'.*\.spec\.js$'],
            'java': [r'.*Test\.java$'],
            'go': [r'.*_test\.go$'],
            'rust': [r'.*_test\.rs$'],
            'cpp': [r'.*_test\.cpp$', r'.*Test\.cpp$'],
            'csharp': [r'.*Test\.cs$']
        }
        
        for lang, patterns in test_patterns.items():
            if lang in self.detected_languages:
                for pattern in patterns:
                    if re.match(pattern, filename):
                        return True
        return False

    def _save_language_and_patch_info(self, waiting_list, conflict_list):
        """Helper method to save language dependency info and patch information"""
        try:
            # Get dependency information for all detected languages
            lang_info = self._get_language_specific_info()
            
            # Save dependency information for each language
            for lang, info in lang_info.items():
                lang_dir = f'{self.root_dir}/output/{self.full_name}/{lang}'
                os.makedirs(lang_dir, exist_ok=True)
                
                # Save dependency information
                if 'deps' in info:
                    for tool, data in info['deps'].items():
                        try:
                            with open(f'{lang_dir}/{tool}.json', 'w') as f:
                                json.dump(data, f, indent=4)
                        except Exception as e:
                            print(f"Error saving {lang} {tool} dependency info: {e}")
                
                # Save version information
                if 'version' in info:
                    try:
                        with open(f'{lang_dir}/version.txt', 'w') as f:
                            f.write(info['version'])
                    except Exception as e:
                        print(f"Error saving {lang} version info: {e}")

            # Save patch information if available
            try:
                generate_diff, generate_diff_return_code = self.sandbox_session.execute('generate_diff', waiting_list, conflict_list)
                if len(generate_diff.strip()) > 0 and generate_diff_return_code == 0:
                    patch_dir = f'{self.root_dir}/output/{self.full_name}/patch'
                    os.makedirs(patch_dir, exist_ok=True)
                    with open(f'{patch_dir}/final_patch.diff', 'w') as w0:
                        w0.write(generate_diff)
            except Exception as e:
                print(f"Error saving patch information: {e}")
        except Exception as e:
            print(f"Error in _save_language_and_patch_info: {e}")

    def run(self, project_path, trajectory, waiting_list, conflict_list):
        print('************** configuration **************')
        print(self.init_prompt)
        start_time0 = time.time()
        self.messages = []
        if "gpt" in self.model:
            system_message = {"role": "system", "content": self.init_prompt}
            self.messages.append(system_message)
            user_message = {"role": "user", "content": f"[Project root Path]: /repo"}
            self.messages.append(user_message)
        else:
            assert "claude" in self.model
            claude_prompt = f"{self.init_prompt} \n[Project root Path]: /repo"
            user_message = {"role": "user", "content": claude_prompt}
            self.messages.append(user_message)

        turn = 0
        cost_tokens = 0
        diff_no = 1
        def manage_token_usage(messages, max_tokens=150000):
            """
            在消息列表超过Token限制时，从最老的消息开始删除，直到总Token数量低于max_tokens。
            使用切片操作来管理Token使用。
            """
            total_tokens = sum(len(str(message)) for message in messages)
            if total_tokens <= max_tokens:
                return messages  # 如果总Token数不超过限制，返回原始消息列表

            # 计算应保留的消息数量
            new_messages = messages[:]
            while sum(len(str(message)) for message in new_messages) > max_tokens:
                # new_messages = new_messages[4:]  # 切片删除最老的消息（不是第0个）
                new_messages = new_messages[:4] + new_messages[6:]

            return new_messages
        
        # 传入内部指令，传出所有正确执行的历史指令
        def extract_cmds(inner_commands):
            res_cmd = list()
            for inner_command in inner_commands:
                command = inner_command['command']
                dir = inner_command['dir'] if 'dir' in inner_command else '/'
                returncode = inner_command['returncode']
                action_name = command.split(' ')[0].strip()
                if str(returncode).strip() != '0':
                    continue
                if action_name in ['pipdeptree']:
                    continue
                if action_name in safe_cmd and '>' not in command:
                    continue
                if command == 'python /home/tools/runtest.py' or command == 'python /home/tools/poetryruntest.py' or command == 'python /home/tools/runpipreqs.py' or command == 'python /home/tools/generate_diff.py' or command == '$pwd$' or command == '$pip list --format json$':
                    continue
                # Exclude all Python tool commands for dependency analysis
                if command.startswith('python /home/tools/') and any(x in command for x in ['cargo_deps.py', 'maven_deps.py', 'gradle_deps.py', 'npm_deps.py', 'go_deps.py']):
                    continue
                if action_name == 'change_python_version':
                    res_cmd = list()
                    continue
                # if action_name == 'change_base_image':
                #     res_cmd = list()
                #     continue
                if action_name == 'clear_configuration':
                    res_cmd = list()
                    continue
                if dir != '/':
                    res_cmd.append(f'cd {dir} && {command}')
                else:
                    res_cmd.append(command)
            return res_cmd

        while(turn < self.max_turn):
            turn += 1
            finish = False
            GPT_start_time = time.time()
            current_messages = manage_token_usage(self.messages)

            configuration_agent_list, usage = get_llm_response(self.model, current_messages)
            # configuration_agent_list, usage = get_llm_response(self.model, self.messages)
            GPT_end_time = time.time()
            GPT_elasped_time = GPT_end_time - GPT_start_time
            self.outer_commands.append({"GPT_time": GPT_elasped_time})
            configuration_agent = configuration_agent_list
            cost_tokens += usage.total_tokens

            # 将模型回答加入记忆
            assistant_message = {"role": "assistant", "content": configuration_agent}
            self.messages.append(assistant_message)
            print('---------------------------')
            print(configuration_agent)
            system_res = '### Observation:\n'
            init_commands = extract_commands(configuration_agent)
            commands = list()
            for ic in init_commands:
                commands.extend(split_cmd_statements(ic))
            diffs = extract_diffs(configuration_agent)
            #如果回答中同时有修改和命令，拒绝
            if len(diffs) != 0 and len(commands) != 0:
                system_res = f"ERROR! Your reply contains both bash block and diff block, which is not accepted. Each round of your reply can only contain one {BASH_FENCE[0]} {BASH_FENCE[1]} block or one {DIFF_FENCE[0]} {DIFF_FENCE[1]} block. Each round of your answers contain only *ONE* action!"
            elif len(commands) != 0: #按顺序执行工具
                for i in range(len(commands)):
                    self.outer_commands.append({"command": commands[i], "returncode": -2, "time": -1})
                    start_time = time.time()
                    vdb = subprocess.run("df -h | grep '/dev/vdb' | awk '{print $5}'", shell=True, capture_output=True, text=True)
                    if vdb.stdout.strip() and float(vdb.stdout.strip().split('%')[0]) > 90:
                        print('Warning! The disk /dev/vdb has occupied over 90% memories!')
                        sys.exit(3)
                    
                    # 切换python版本
                    if commands[i].strip().startswith('change_python_version'):
                        python_version = commands[i].strip().split('change_python_version')[1].strip()
                        try:
                            sandbox = self.sandbox_session.sandbox.change_python_version(python_version)
                            if isinstance(sandbox, str):
                                print(sandbox)
                                system_res += sandbox
                            else:
                                self.sandbox = sandbox
                                self.sandbox_session = self.sandbox.get_session()
                                res = f"You have successfully switched the docker container's Python version to {python_version}. If you want to revert to the previous environment, you can enter `change_python_version` followed by the previous python version."
                                # 内部指令需要添加一个标志
                                self.sandbox.commands.append({"command": f'change_python_version {python_version}', "returncode": 0, "time": -1})
                                self.image_name = 'python:' + python_version
                                print(res)
                                system_res += res
                        except Exception as e:
                            res = f"Error to change the docker container's Python version to {python_version}, the error messages are: {e}"
                            print(res)
                            self.outer_commands[-1]["returncode"] = 1
                            system_res += res
                        end_time = time.time()
                        elasped_time = end_time - start_time
                        self.outer_commands[-1]["time"] = elasped_time
                        self.outer_commands[-1]["returncode"] = 0
                        if self.sandbox.commands[-1]['command'] == f'change_python_version {python_version}':
                            self.sandbox.commands[-1]["time"] = elasped_time
                        continue
                    
                    # 恢复最初版本
                    if commands[i].strip() == 'clear_configuration':
                        try:
                            sandbox = self.sandbox_session.sandbox.change_python_version('3.10')
                            self.sandbox = sandbox
                            self.sandbox_session = self.sandbox.get_session()
                            res = f"You have successfully switched the docker container's Python version to 3.10. If you want to revert to the previous environment, you can enter `change_python_version` followed by the previous python version."
                            # 内部指令需要添加一个标志
                            self.sandbox.commands.append({"command": f'clear_configuration', "returncode": 0, "time": -1})
                            self.image_name = 'python:3.10'
                            print(res)
                            system_res += res
                        except Exception as e:
                            res = f"Error to change the docker container's Python version to 3.10, the error messages are: {e}"
                            print(res)
                            self.outer_commands[-1]["returncode"] = 1
                            system_res += res
                        end_time = time.time()
                        elasped_time = end_time - start_time
                        self.outer_commands[-1]["time"] = elasped_time
                        self.outer_commands[-1]["returncode"] = 0
                        if self.sandbox.commands[-1]['command'] == f'clear_configuration':
                            self.sandbox.commands[-1]["time"] = elasped_time
                        continue

                    sandbox_res, return_code =  self.sandbox_session.execute(commands[i], waiting_list, conflict_list)
                    sandbox_res = res_truncate(sandbox_res)
                    system_res += sandbox_res
                    if return_code != 'unknown':
                        system_res += f'\n`{commands[i]}` executes with returncode: {return_code}\n'
                    end_time = time.time()
                    elasped_time = end_time - start_time
                    self.outer_commands[-1]["time"] = elasped_time
                    self.outer_commands[-1]["returncode"] = 0
                    #重置session
                    if TIME_OUT_LABEL in sandbox_res:
                        self.sandbox_session = self.sandbox.get_session()
                        self.outer_commands[-1]["returncode"] = 1
                    if 'Congratulations' in sandbox_res:  # Generic success condition
                        self._save_language_and_patch_info(waiting_list, conflict_list)  # Keep this call for successful completion
                        print(sandbox_res)
                        with open(f'{self.root_dir}/output/{self.full_name}/test.txt', 'w') as w3:
                            w3.write('\n'.join(sandbox_res.splitlines()[1:]))
                        finish = True
                        break
                if finish:
                    break
            elif len(diffs) != 0:
                filename = diffs.split('<<<<<<< SEARCH')[0].split('/')[-1].strip()
                if self._is_test_file(filename):
                    self.outer_commands.append({"diff": diffs, "returncode": -2, "time": -1})
                    system_res += ('Running Edit...\n' + 
                                  f"You are trying to modify test file {filename}, but modifying test files is not allowed. " +
                                  "Please consider alternative solutions.\n")
                else:
                    self.outer_commands.append({"diff": diffs, "returncode": -2, "time": -1})
                    start_time = time.time()
                    tmp_name = save_diff_description(diffs)
                    sandbox_res, return_code =  self.sandbox_session.edit(tmp_name, project_path)
                    end_time = time.time()
                    elasped_time = end_time - start_time
                    self.outer_commands[-1]["returncode"] = 0
                    self.outer_commands[-1]["time"] = elasped_time
                    if return_code == 0:
                        try:
                            generate_diff, generate_diff_return_code = self.sandbox_session.execute('generate_diff', waiting_list, conflict_list)
                        except Exception as e:
                            print(f'Generate diff wrong: {e}!')
                        # if len(generate_diff.strip()) > 0 and generate_diff_return_code == 0:
                        if not os.path.exists(f'{self.root_dir}/output/{self.full_name}/patch'):
                            os.system(f'mkdir {self.root_dir}/output/{self.full_name}/patch')
                        with open(f'{self.root_dir}/output/{self.full_name}/patch/patch_{diff_no}.diff', 'w') as w0:
                            w0.write(generate_diff + '\n')
                        diff_no += 1
                    system_res += sandbox_res
                    #重置session
                    if TIME_OUT_LABEL in sandbox_res:
                        self.sandbox_session =  self.sandbox.get_session()
                    if HEAD not in diffs or DIVIDER not in diffs or UPDATED not in diffs:
                        self.outer_commands[-1]["returncode"] = 1
                        system_res += f"""#### Your patch is incomplete with {HEAD} or {DIVIDER} or {UPDATED} missing! ####            
The edit format is as follows: 

{DIFF_FENCE[0]}
/absolute/path/of/target.py
{HEAD}
    exact copy of old line(s) you would like to change
{DIVIDER}
    new line(s) to replace
{UPDATED}
"""
            else:
                self.outer_commands[-1]["returncode"] = 2
                system_res += "ERROR! Your reply does not contain valid block or final answer."
            
            current_directory, return_code = self.sandbox_session.execute('$pwd$', waiting_list, conflict_list)
            current_directory = '\n[Current directory]:\n' + current_directory + '\n'
            system_res += current_directory
            system_res += f'You are currently in a [{self.image_name}] container.\n'
            reminder = f"\nENVIRONMENT REMINDER: You have {self.max_turn - turn} turns left to complete the task."
            system_res += reminder
            success_cmds = extract_cmds(self.sandbox.commands)


            if len(success_cmds) > 0:
                appendix = '\nThe container has successfully executed the following commands in order. Please refer to the execution history, reflect, and decide the subsequent actions. Remember, your ultimate goal is to pass the tests by executing the provided test commands.\n' + \
                    '\n'.join(success_cmds)
            else:
                appendix = '\nThe container remains in its original state.'
            pattern = r'python\s+/home/tools/pip_download.py\s+-p\s+(\S+)\s+-v\s+""([^""]+)""'

            replacement = r'pip install \1\2'
            appendix = re.sub(pattern, replacement, appendix)

            pattern1 = r'python\s+/home/tools/pip_download.py\s+-p\s+(\S+)'
            replacement1 = r'pip install \1'
            appendix = re.sub(pattern1, replacement1, appendix)
            
            system_res += appendix
            if "gpt" in self.model:
                system_message = {"role": "system", "content": system_res}
            else:
                system_message = {"role": "user", "content": system_res}
            self.messages.append(system_message)
            with open(f'{self.root_dir}/output/{self.full_name}/outer_commands.json', 'w') as w1:
                w1.write(json.dumps(self.outer_commands, indent=4))
            with open(f'{self.root_dir}/output/{self.full_name}/inner_commands.json', 'w') as w1:
                w1.write(json.dumps(self.sandbox.commands, indent=4))
            print(system_res)

        append_trajectory(trajectory, self.messages, 'configuration')
        end_time0 = time.time()
        cost_time = end_time0 - start_time0
        trajectory.append({'agent': "configuration", 'cost_time': cost_time, 'cost_tokens': cost_tokens}) 
        self.sandbox_session.close()
        return trajectory, self.outer_commands