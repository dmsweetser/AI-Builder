import os
import re
import logging
import shutil
import subprocess
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential
from llama_cpp import Llama
from config import Config

# Load environment variables from .env file
load_dotenv()

class FileParser:
    @staticmethod
    def parse_custom_format(content: str) -> List[Dict[str, Any]]:
        try:
            if "</think>" in content:
                content = content.split("</think>")[1]
            content = re.sub(r'^.*?\[aibuilder_change', '[aibuilder_change', content, flags=re.DOTALL)
            changes = []
            change_blocks = re.finditer(
                r'\[aibuilder_change\s+file\s*=\s*"([^"]+)"\](.*?)(?=\[aibuilder_change|$)',
                content,
                re.DOTALL
            )
            for block in change_blocks:
                file = block.group(1)
                actions = FileParser._parse_actions(block.group(2))
                changes.append({'file': file, 'actions': actions})
            return changes
        except Exception as e:
            logging.error(f"Error parsing custom format: {e}")
            raise

    @staticmethod
    def _parse_actions(content: str) -> List[Dict[str, Any]]:
        try:
            actions = []
            action_blocks = re.finditer(
                r'\[aibuilder_action\s+type\s*=\s*"([^"]+)"\](.*?)\[aibuilder_end_action\]',
                content,
                re.DOTALL
            )
            for action_block in action_blocks:
                action_type = action_block.group(1)
                action_content = action_block.group(2)
                if action_type == 'create_file':
                    action = FileParser._parse_create_action(action_content)
                elif action_type == 'remove_file':
                    action = {'action': 'remove_file'}
                elif action_type == 'replace_file':
                    action = FileParser._parse_replace_file_action(action_content)
                elif action_type == 'replace_section':
                    action = FileParser._parse_replace_section_action(action_content)
                else:
                    continue
                if action:
                    actions.append(action)
            return actions
        except Exception as e:
            logging.error(f"Error parsing actions: {e}")
            raise

    @staticmethod
    def _parse_create_action(content: str) -> Optional[Dict[str, Any]]:
        try:
            file_content_pattern = r'\[aibuilder_file_content\](.*?)\[aibuilder_end_file_content\]'
            file_content_match = re.search(file_content_pattern, content, re.DOTALL)
            if file_content_match:
                return {
                    'action': 'create_file',
                    'file_content': file_content_match.group(1).strip().split('\n')
                }
            return None
        except Exception as e:
            logging.error(f"Error parsing create action: {e}")
            raise

    @staticmethod
    def _parse_replace_file_action(content: str) -> Optional[Dict[str, Any]]:
        try:
            file_content_pattern = r'\[aibuilder_file_content\](.*?)\[aibuilder_end_file_content\]'
            file_content_match = re.search(file_content_pattern, content, re.DOTALL)
            if file_content_match:
                return {
                    'action': 'replace_file',
                    'file_content': file_content_match.group(1).strip().split('\n')
                }
            return None
        except Exception as e:
            logging.error(f"Error parsing replace file action: {e}")
            raise

    @staticmethod
    def _parse_replace_section_action(content: str) -> Optional[Dict[str, Any]]:
        try:
            original_content_pattern = r'\[aibuilder_original_content\](.*?)\[aibuilder_end_original_content\]'
            file_content_pattern = r'\[aibuilder_file_content\](.*?)\[aibuilder_end_file_content\]'
            original_content_match = re.search(original_content_pattern, content, re.DOTALL)
            file_content_match = re.search(file_content_pattern, content, re.DOTALL)
            if original_content_match and file_content_match:
                return {
                    'action': 'replace_section',
                    'original_content': original_content_match.group(1).strip(),
                    'file_content': file_content_match.group(1).strip().split('\n')
                }
            return None
        except Exception as e:
            logging.error(f"Error parsing replace section action: {e}")
            raise

class FileModifier:
    @staticmethod
    def apply_modifications(changes: List[Dict[str, Any]], dry_run: bool = False) -> List[Dict[str, Any]]:
        try:
            incomplete_actions = []
            for change in changes:
                filepath = change['file']
                backup_filepath = f"{filepath}.bak"
                logging.info(f"Processing file: {filepath}")
                if not dry_run:
                    try:
                        if os.path.exists(filepath):
                            shutil.copy2(filepath, backup_filepath)
                            logging.info(f"Created backup: {backup_filepath}")
                    except Exception as e:
                        logging.error(f"Could not back up file: {filepath}: {e}")
                for action in change['actions']:
                    try:
                        if dry_run:
                            logging.info(f"Dry run: Would apply action {action['action']} to {filepath}")
                        else:
                            if not FileModifier._apply_action(filepath, action):
                                incomplete_actions.append({'file': filepath, 'action': action})
                    except Exception as e:
                        logging.error(f"Error applying modifications to {filepath}: {e}")
                        incomplete_actions.append({'file': filepath, 'action': action})
                        if not dry_run and os.path.exists(backup_filepath):
                            shutil.copy2(backup_filepath, filepath)
                            logging.info(f"Restored backup for {filepath}")
            return incomplete_actions
        except Exception as e:
            logging.error(f"Error applying modifications: {e}")
            raise

    @staticmethod
    def _apply_action(filepath: str, action: Dict[str, Any]) -> bool:
        try:
            action_type = action['action']
            if os.path.dirname(filepath) != "":
                os.makedirs(os.path.dirname(filepath), exist_ok=True)

            if action_type == 'create_file':
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write("\n".join(action['file_content']) + "\n")
                logging.info(f"Created/Replaced: {filepath}")
                return True
            elif action_type == 'remove_file':
                if os.path.isfile(filepath):
                    os.remove(filepath)
                    logging.info(f"Removed: {filepath}")
                    return True
                else:
                    logging.warning(f"File not found: {filepath}")
                    return False
            elif action_type == 'replace_file':
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write("\n".join(action['file_content']) + "\n")
                logging.info(f"Replaced entire content of: {filepath}")
                return True
            elif action_type == 'replace_section':
                return FileModifier._replace_section(filepath, action['original_content'], action['file_content'])
            return False
        except Exception as e:
            logging.error(f"Error applying action: {e}")
            raise

    @staticmethod
    def _replace_section(filepath: str, original_content: str, new_content: List[str]) -> bool:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            new_section_str = '\n'.join(new_content)
            if original_content in content:
                modified_content = content.replace(original_content, new_section_str)
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(modified_content)
                logging.info(f"Replaced section in: {filepath}")
                return True
            else:
                logging.warning(f"Original content not found in: {filepath}")
                return False
        except Exception as e:
            logging.error(f"Error replacing section: {e}")
            raise

class ActionManager:
    @staticmethod
    def save_actions(actions: List[Dict[str, Any]], filepath: str) -> None:
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                for action in actions:
                    f.write(f"File: {action['file']}\n")
                    f.write(f"Action: {action['action']['action']}\n")
                    if action['action']['action'] in ['create_file', 'replace_file', 'replace_section']:
                        f.write("Content:\n")
                        f.write("\n".join(action['action']['file_content']) + "\n")
                    if action['action']['action'] == 'replace_section':
                        f.write(f"Original Content:\n{action['action']['original_content']}\n")
                    f.write("\n")
            logging.info(f"Saved actions to {filepath}")
        except Exception as e:
            logging.error(f"Error saving actions: {e}")
            raise

    @staticmethod
    def load_actions(filepath: str) -> List[Dict[str, Any]]:
        try:
            actions = []
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                action_blocks = re.finditer(
                    r'File: (.*?)\nAction: (.*?)\n(?:Content:\n(.*?)(?=\nFile:|\Z))?(?:Original Content:\n(.*?)(?=\nFile:|\Z))?',
                    content,
                    re.DOTALL
                )
                for block in action_blocks:
                    file = block.group(1)
                    action_type = block.group(2)
                    file_content = block.group(3).strip().split('\n') if block.group(3) else []
                    original_content = block.group(4).strip() if block.group(4) else None
                    action = {'action': action_type}
                    if action_type in ['create_file', 'replace_file', 'replace_section']:
                        action['file_content'] = file_content
                    if action_type == 'replace_section':
                        action['original_content'] = original_content
                    actions.append({'file': file, 'action': action})
            logging.info(f"Loaded actions from {filepath}")
            return actions
        except Exception as e:
            logging.error(f"Error loading actions: {e}")
            raise

class CodeUtility:
    def __init__(self, base_dir: str = os.getcwd()):
        self.base_dir = base_dir
        self.output_file = os.path.join(base_dir, "ai_builder", "output.txt")
        self.response_file = os.path.join(base_dir, "ai_builder", "current_response.txt")
        self.log_file = os.path.join(base_dir, "ai_builder", "utility.log")

    def parse_gitignore(self, directory: str) -> List[str]:
        try:
            gitignore_path = os.path.join(directory, ".gitignore")
            if os.path.exists(gitignore_path):
                with open(gitignore_path, 'r', encoding='utf-8') as file:
                    return [line.strip() for line in file if line.strip() and not line.strip().startswith('#')]
            return []
        except Exception as e:
            logging.error(f"Error parsing .gitignore: {e}")
            raise

    def should_process_file(self, path: str, rules: List[str], patterns: List[str], mode: str) -> bool:
        try:
            file_name = os.path.basename(path)
            for rule in rules:
                if rule in path:
                    return False
            for pattern in patterns:
                if pattern in file_name or pattern in path:
                    return mode == "include"
            return mode == "exclude"
        except Exception as e:
            logging.error(f"Error determining if file should be processed: {e}")
            raise

    def process_directory(self, directory: str, parent_rules: List[str], patterns: List[str], mode: str) -> None:
        try:
            current_rules = self.parse_gitignore(directory)
            all_rules = parent_rules + current_rules
            logging.info(f"Processing directory: {directory}")
            for root, _, files in os.walk(directory):
                for file in files:
                    relative_path = os.path.relpath(os.path.join(root, file), self.base_dir)
                    logging.info(f"Checking file: {relative_path}")
                    if self.should_process_file(relative_path, all_rules, patterns, mode):
                        try:
                            file_path = os.path.join(root, file)
                            with open(file_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                            with open(self.output_file, 'a', encoding='utf-8') as out_file:
                                out_file.write(f"\n### {relative_path}\n```\n{content}\n```\n")
                            logging.info(f"Successfully wrote content from {relative_path} to {self.output_file}")
                        except Exception as e:
                            logging.warning(f"Skipped unreadable file: {relative_path} - Error: {e}")
        except Exception as e:
            logging.error(f"Error processing directory: {e}")
            raise

class AIBuilder:
    def __init__(self):
        self.return_git_diff = True
        self.root_directory = Config.get_root_directory()
        self.ai_builder_dir = Config.get_ai_builder_dir(self.root_directory)
        os.makedirs(self.ai_builder_dir, exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(Config.get_log_file_path(self.root_directory)),
                logging.StreamHandler()
            ]
        )

    def run_pre_post_scripts(self, script_name: str) -> None:
        try:
            script_path = os.path.join(os.getcwd(), script_name)
            if not os.path.exists(script_path):
                raise FileNotFoundError(f"Script {script_name} not found.")
            subprocess.run(["powershell", "-File", script_path], check=True)
            logging.info(f"Successfully executed {script_name}")
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to execute {script_name}: {e}")
            raise
        except Exception as e:
            logging.error(f"Error executing script {script_name}: {e}")
            raise

    def cleanup_bak_files(self) -> None:
        try:
            for root, _, files in os.walk(self.root_directory):
                for file in files:
                    if file.endswith('.bak'):
                        file_path = os.path.join(root, file)
                        try:
                            os.remove(file_path)
                            logging.info(f"Removed backup file: {file_path}")
                        except Exception as e:
                            logging.error(f"Error removing backup file {file_path}: {e}")
        except Exception as e:
            logging.error(f"Error cleaning up backup files: {e}")
            raise

    def run(self) -> None:
        try:
            base_config_path = os.path.join("base_config.xml")
            user_config_path = os.path.join(self.ai_builder_dir, "user_config.xml")
            if os.path.exists(base_config_path) and not os.path.exists(user_config_path):
                shutil.copy(base_config_path, user_config_path)
                logging.info("Copied base_config.xml to user_config.xml")
            elif not os.path.exists(base_config_path):
                default_config = """<?xml version="1.0" encoding="UTF-8"?>
<config>
    <iterations>1</iterations>
    <mode>exclude</mode>
    <patterns>
        <pattern>package-lock.json</pattern>
        <pattern>output.txt</pattern>
        <pattern>full_request.txt</pattern>
        <pattern>full_response.txt</pattern>
        <pattern>instructions.txt</pattern>
        <pattern>changes.patch</pattern>
        <pattern>.git</pattern>
        <pattern>utility.log</pattern>
        <pattern>.png</pattern>
        <pattern>.exe</pattern>
        <pattern>.ico</pattern>
        <pattern>.webp</pattern>
        <pattern>.gguf</pattern>
    </patterns>
</config>"""
                with open(user_config_path, 'w', encoding='utf-8') as config_file:
                    config_file.write(default_config)
                logging.warning("base_config.xml not found, created default user_config.xml")

            pre_script_path = os.path.join(self.root_directory, "pre.ps1")
            post_script_path = os.path.join(self.root_directory, "post.ps1")
            instructions_path = os.path.join(self.root_directory, "instructions.txt")
            if not all(os.path.exists(path) for path in [pre_script_path, post_script_path, instructions_path]):
                raise FileNotFoundError("Pre script, post script, or instructions file not found.")

            os.chdir(self.root_directory)
            logging.info(f"Changed working directory to: {self.root_directory}")
            self.utility = CodeUtility(self.root_directory)
            config = ET.parse(user_config_path).getroot()
            iterations = int(config.find('iterations').text)
            mode = config.find('mode').text
            patterns = [pattern.text for pattern in config.findall('patterns/pattern')]
            actions_file_path = os.path.join(self.ai_builder_dir, "actions.txt")

            for iteration in range(iterations):
                logging.info(f"Starting iteration {iteration + 1}")
                self.run_pre_post_scripts("pre.ps1")
                try:
                    modifications_format_path = os.path.join(self.ai_builder_dir, "modifications.txt")
                    if not os.path.exists(modifications_format_path):
                        if os.path.exists(self.utility.output_file):
                            os.remove(self.utility.output_file)
                        self.utility.process_directory(self.root_directory, [], patterns, mode)
                        if not os.path.exists(self.utility.output_file):
                            logging.warning("output.txt was not created by process_directory.")
                            continue

                        if Config.generate_output_only():
                            return

                        with open(self.utility.output_file, 'r', encoding='utf-8') as file:
                            current_code = file.read().strip()
                        logging.info("Successfully read output.txt")
                        with open('instructions.txt', 'r', encoding='utf-8') as file:
                            instructions = file.read().strip()
                        logging.info("Successfully read instructions.txt")

                        prompt = f"""
Generate a line-delimited format file that describes file modifications to apply using the `create_file`, `remove_file`, `replace_file`, and `replace_section` action types.
Ensure all content is provided using line-delimited format-compatible entities.
Focus on small, specific sections of code rather than large blocks.
Ensure you do not omit any existing code and only modify the sections specified.
Available operations:
1. `create_file`:
    - `file_content`: List of strings (lines of the file content)
2. `remove_file`:
    - No additional parameters needed.
3. `replace_file`:
    - `file_content`: List of strings (lines of the new file content)
    - The revision must be entirely complete
4. `replace_section`:
    - `original_content`: The original content in the file
    - `file_content`: List of strings (lines of the new file content to replace the original content)
Example output format:
[aibuilder_change file="new_file.py"]
[aibuilder_action type="create_file"]
[aibuilder_file_content]
# Content line 1 with whitespace preserved
\t# Content line 2 with whitespace preserved
\t# Content line 3 with whitespace preserved
[aibuilder_end_file_content]
[aibuilder_end_action]
[aibuilder_change file="old_file.py"]
[aibuilder_action type="remove_file"]
[aibuilder_end_action]
[aibuilder_change file="file_to_replace.py"]
[aibuilder_action type="replace_file"]
[aibuilder_file_content]
# New content line 1 with whitespace preserved
\t# New content line 2 with whitespace preserved
\t# New content line 3 with whitespace preserved
[aibuilder_end_file_content]
[aibuilder_end_action]
[aibuilder_change file="file_to_modify.py"]
[aibuilder_action type="replace_section"]
[aibuilder_original_content]
# Original content line 1
\t# Original content line 2
[aibuilder_end_original_content]
[aibuilder_file_content]
# New content line 1 with whitespace preserved
\t# New content line 2 with whitespace preserved
\t# New content line 3 with whitespace preserved
[aibuilder_end_file_content]
[aibuilder_end_action]
Generate modifications logically based on the desired changes.
Current code:
{current_code}
Instructions:
{instructions}
Reply ONLY in the specified format with no commentary. THAT'S AN ORDER, SOLDIER!
"""

                        use_local_model = Config.use_local_model()
                        if use_local_model:
                            model_path = Config.get_model_path()
                            if not model_path:
                                logging.error("MODEL_PATH environment variable not set for local model.")
                                raise ValueError("MODEL_PATH environment variable not set.")
                            llm = Llama(
                                model_path=model_path,
                                n_ctx=Config.get_model_context()
                            )
                            response_content = ""
                            current_iteration = 0
                            for response in llm.create_completion(
                                prompt,
                                temperature=Config.get_temperature(),
                                top_p=Config.get_top_p(),
                                top_k=Config.get_top_k(),                                
                                min_p=Config.get_min_p(),
                                max_tokens=Config.get_output_tokens(),
                                stream=True
                            ):
                                token = response['choices'][0]['text']
                                response_content += token
                                if current_iteration % 100 == 0:
                                    with open(self.response_file, 'a', encoding='utf-8') as response_log:
                                        response_log.write(response_content)
                                current_iteration = current_iteration + 1
                        else:
                            endpoint = Config.get_endpoint()
                            model_name = Config.get_model_name()
                            api_key = Config.get_api_key()
                            if not all([endpoint, model_name, api_key]):
                                logging.error("Missing one or more required environment variables: ENDPOINT, MODEL_NAME, API_KEY")
                                raise ValueError("Missing required environment variables.")
                            client = ChatCompletionsClient(
                                endpoint=endpoint,
                                credential=AzureKeyCredential(api_key),
                                api_version="2024-05-01-preview"
                            )
                            response = client.complete(
                                stream=True,
                                messages=[
                                    SystemMessage(content="You are a helpful assistant."),
                                    UserMessage(content=prompt)
                                ],
                                max_tokens=Config.get_output_tokens(),
                                model=model_name
                            )
                            response_content = ""
                            try:
                                for update in response:
                                    if update.choices and isinstance(update.choices, list) and len(update.choices) > 0:
                                        content = update.choices[0].get("delta", {}).get("content", "")
                                        if content is not None:
                                            response_content += content
                                    else:
                                        break
                            finally:
                                response.close()

                        logging.info("Successfully obtained response from client.")
                        with open(modifications_format_path, 'w', encoding='utf-8') as modifications_file:
                            modifications_file.write(response_content)
                        logging.info(f"Successfully wrote modifications file to {modifications_format_path}")
                    else:
                        with open(modifications_format_path, 'r', encoding='utf-8') as modifications_file:
                            response_content = modifications_file.read()

                    if not Config.generate_but_do_not_apply():
                        changes = FileParser.parse_custom_format(response_content)
                        incomplete_actions = FileModifier.apply_modifications(changes, dry_run=False)
                        ActionManager.save_actions(incomplete_actions, actions_file_path)

                except Exception as e:
                    logging.error(f"An error occurred: {str(e)}", exc_info=True)

                self.run_pre_post_scripts("post.ps1")
                self.cleanup_bak_files()

        except Exception as e:
            logging.error(f"An error occurred during execution: {str(e)}", exc_info=True)

if __name__ == "__main__":
    try:
        ai_builder = AIBuilder()
        ai_builder.run()
    except Exception as e:
        logging.error(f"An error occurred during AIBuilder execution: {str(e)}", exc_info=True)
