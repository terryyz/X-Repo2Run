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
from utils.agent_util import safe_cmd, extract_commands, append_trajectory, TIME_OUT_LABEL, BASH_FENCE
from utils.split_cmd import split_cmd_statements
import time
from utils.repo_utils import get_repo_structure, find_main_readme

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
    # Traverse each keyword and find its positions in the text
    all_positions = {}
    for keyword in keywords:
        positions = [i for i in range(len(text)) if text.startswith(keyword, i)]
        if len(positions) > 1:
            all_positions[keyword] = positions

    if not all_positions:
        return text

    # Process each keyword position starting from the end of the result text, keeping only the last one
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
        self.root_dir = root_dir
        self.max_turn = max_turn
        self.sandbox = sandbox
        self.sandbox_session = self.sandbox.get_session()
        self.full_name = full_name
        self.image_name = image_name
        self.outer_commands = list()
        
        # Initialize prompt
        self.init_prompt = self._generate_init_prompt()
        
    def _generate_init_prompt(self):
        """Generate the initial prompt with repository information."""
        repo_path = f'{self.root_dir}/utils/repo/{self.full_name}/repo'
        
        # Get repository structure
        repo_structure = get_repo_structure(repo_path)
        
        # Get README content
        readme_info = find_main_readme(repo_path)
        readme_content = readme_info.get('content', 'README not found')
        readme_path = readme_info.get('path', '')
        
        # Construct the prompt
        prompt = f"""You are an agent tasked with launching a web UI from the repository.

YOUR GOAL IS TO LAUNCH THE WEB UI AND TELL THE USER WHERE IT'S RUNNING.

REPOSITORY INFORMATION:
Full Name: {self.full_name}

REPOSITORY STRUCTURE:
{repo_structure}

README {f'({readme_path})' if readme_path else ''}:
{readme_content}

The repository is mounted at /repo in the Docker container. You can run any shell commands to explore the repository, install dependencies, and launch the web application.

INSTRUCTIONS:
1. FIRST, thoroughly analyze the README to understand the repository's purpose and setup requirements.
2. If you encounter any errors during execution, analyze them and attempt to fix the issues.
3. When you have successfully launched the web application, report SUCCESS.
4. If you determine that no web UI can be launched after thorough investigation, report FAILURE.

Use the following format for your interaction:
### Thought: [Detailed reasoning about your current understanding, interpretation of README/shell responses, and next steps]
### Action:
{BASH_FENCE[0]}
[your command]
{BASH_FENCE[1]}

When executing multiple related commands, connect them with `&&` or `&& \` rather than creating separate Action blocks:
{BASH_FENCE[0]}
cd /repo && ls -l && pip install numpy
{BASH_FENCE[1]}

When you have successfully launched the web application, use this format:
### Thought: [Detailed explanation of how you determined the web UI is running successfully]
### SUCCESS:
- url: http://[host]:[port]
- description: [Brief description of what's running]

If you determine no web UI can be launched, use this format:
### Thought: [Detailed explanation of why you concluded a web UI cannot be launched]
### FAILURE:
- reason: [Detailed explanation of why a web UI cannot be launched]
- suggestion: [Alternative approaches if applicable]

IMPORTANT NOTES:
- You MUST verify the application is running before reporting success
- For HTML applications, typically you do not need to install dependencies, just launch a web server
- For complex setup procedures, use `&&` to connect related commands rather than separating them into multiple Action blocks
- For long commands, you can use `&& \` for line continuation while keeping commands in a single execution block
- When starting a web server:
    - You must run it on the background (e.g., using `&` or `nohup`)
    - Make sure to specify the log file location so you can check the server's output
    - Sleep an appropriate amount of time to ensure the server has started successfully
    - You can verify the server is running by checking the logs or using `curl` to access the URL
    - If the server fails to start, analyze the logs to fix the issue
"""
        return prompt
    
    def show_init_prompt(self):
        print(self.init_prompt)
    
    def get_max_turn(self):
        return self.max_turn

    def run(self, project_path, trajectory, waiting_list, conflict_list):
        print('************** simple agent **************')
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
        
        def manage_token_usage(messages, max_tokens=150000):
            """
            Delete older messages when the token limit is exceeded, starting from the oldest message.
            """
            total_tokens = sum(len(str(message)) for message in messages)
            if total_tokens <= max_tokens:
                return messages  # If the total token count doesn't exceed the limit, return the original messages

            # Calculate the number of messages to keep
            new_messages = messages[:]
            while sum(len(str(message)) for message in new_messages) > max_tokens:
                new_messages = new_messages[:4] + new_messages[6:]

            return new_messages
        
        # Extract all correctly executed commands
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
                if command == 'python /home/tools/runtest.py' or command == 'python /home/tools/poetryruntest.py' or command == 'python /home/tools/runpipreqs.py' or command == '$pwd$' or command == '$pip list --format json$':
                    continue
                if dir != '/':
                    res_cmd.append(f'cd {dir} && {command}')
                else:
                    res_cmd.append(command)
            return res_cmd

        while(turn < self.max_turn):
            turn += 1
            GPT_start_time = time.time()
            current_messages = manage_token_usage(self.messages)

            agent_response_list, usage = get_llm_response(self.model, current_messages)
            GPT_end_time = time.time()
            GPT_elasped_time = GPT_end_time - GPT_start_time
            self.outer_commands.append({"GPT_time": GPT_elasped_time})
            agent_response = agent_response_list
            cost_tokens += usage.total_tokens

            # Add model response to memory
            assistant_message = {"role": "assistant", "content": agent_response}
            self.messages.append(assistant_message)
            print('---------------------------')
            print(agent_response)
            
            # Check for SUCCESS or FAILURE pattern
            if "### SUCCESS:" in agent_response:
                print(f"SUCCESS detected in agent response")

                # Extract the URL from the SUCCESS block using the known format
                success_lines = agent_response.split('### SUCCESS:')[1].strip().split('\n')
                for line in success_lines:
                    if line.startswith('- url:'):
                        success_url = line.replace('- url:', '').strip()
                        try:
                            # Execute curl inside the container to get the HTML content
                            curl_command = f'curl -s {success_url}'
                            html_content, _ = self.sandbox_session.execute(curl_command, waiting_list, conflict_list)
                            
                            # Save the HTML content to a file
                            with open(f'{self.root_dir}/output/{self.full_name}/webpage.html', 'w') as html_file:
                                html_file.write(html_content)
                            print(f"Saved webpage HTML content to webpage.html")
                        except Exception as e:
                            print(f"Error capturing webpage content: {str(e)}")
                        break
        
                with open(f'{self.root_dir}/output/{self.full_name}/test.txt', 'w') as w3:
                    w3.write(agent_response)
                break
            
            if "### FAILURE:" in agent_response:
                print(f"FAILURE detected in agent response")
                with open(f'{self.root_dir}/output/{self.full_name}/test.txt', 'w') as w3:
                    w3.write(agent_response)
                break
            
            system_res = '### Observation:\n'
            init_commands = extract_commands(agent_response)
            commands = list()
            for ic in init_commands:
                commands.extend(split_cmd_statements(ic))
            
            if len(commands) != 0:  # Execute tools in order
                for i in range(len(commands)):
                    self.outer_commands.append({"command": commands[i], "returncode": -2, "time": -1})
                    start_time = time.time()
                    vdb = subprocess.run("df -h | grep '/dev/vdb' | awk '{print $5}'", shell=True, capture_output=True, text=True)
                    if vdb.stdout.strip() and float(vdb.stdout.strip().split('%')[0]) > 90:
                        print('Warning! The disk /dev/vdb has occupied over 90% memories!')
                        sys.exit(3)

                    # Execute the command in the sandbox
                    sandbox_res, return_code = self.sandbox_session.execute(commands[i], waiting_list, conflict_list)
                    sandbox_res = res_truncate(sandbox_res)
                    system_res += sandbox_res
                    if return_code != 'unknown':
                        system_res += f'\n`{commands[i]}` executes with returncode: {return_code}\n'
                    end_time = time.time()
                    elasped_time = end_time - start_time
                    self.outer_commands[-1]["time"] = elasped_time
                    self.outer_commands[-1]["returncode"] = 0
                    
                    # Reset session if timeout occurred
                    if TIME_OUT_LABEL in sandbox_res:
                        self.sandbox_session = self.sandbox.get_session()
                        self.outer_commands[-1]["returncode"] = 1
                    
            else:
                self.outer_commands[-1]["returncode"] = 2
                system_res += "ERROR! Your reply does not contain valid command block. You must provide shell commands or report SUCCESS/FAILURE."
            
            # Get current directory information
            current_directory, return_code = self.sandbox_session.execute('$pwd$', waiting_list, conflict_list)
            current_directory = '\n[Current directory]:\n' + current_directory + '\n'
            system_res += current_directory
            system_res += f'You are currently in a [{self.image_name}] container.\n'
            reminder = f"\nENVIRONMENT REMINDER: You have {self.max_turn - turn} turns left to complete the task."
            system_res += reminder
            success_cmds = extract_cmds(self.sandbox.commands)

            if len(success_cmds) > 0:
                appendix = '\nThe container has successfully executed the following commands in order. Please refer to the execution history, reflect, and decide the subsequent actions.\n' + \
                    '\n'.join(success_cmds)
            else:
                appendix = '\nThe container remains in its original state.'
            
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
                
        append_trajectory(trajectory, self.messages, 'simple_agent')
        end_time0 = time.time()
        cost_time = end_time0 - start_time0
        trajectory.append({'agent': "simple_agent", 'cost_time': cost_time, 'cost_tokens': cost_tokens}) 
        self.sandbox_session.close()
        return trajectory, self.outer_commands