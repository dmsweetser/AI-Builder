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

# Load environment variables from .env file
load_dotenv()
root_directory = os.getenv("ROOT_DIRECTORY", os.getcwd())
ai_builder_dir = os.path.join(root_directory, "ai_builder")
os.makedirs(ai_builder_dir, exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(ai_builder_dir + '/utility.log'),
        logging.StreamHandler()
    ]
)

class FileParser:
    @staticmethod
    def parse_custom_format(content: str) -> List[Dict[str, Any]]:
        changes = []
        change_blocks = re.finditer(
            r'\[aibuilder_change file="([^"]+)"\](.*?)\[/aibuilder_change\]',
            content,
            re.DOTALL
        )
        for block in change_blocks:
            file = block.group(1)
            actions = FileParser._parse_actions(block.group(2))
            changes.append({'file': file, 'actions': actions})
        return changes

    @staticmethod
    def _parse_actions(content: str) -> List[Dict[str, Any]]:
        actions = []
        action_blocks = re.finditer(
            r'\[aibuilder_action type="([^"]+)"\](.*?)\[/aibuilder_action\]',
            content,
            re.DOTALL
        )
        for action_block in action_blocks:
            action_type = action_block.group(1)
            action_content = action_block.group(2)
            if action_type == 'replace_between_markers_exclusive':
                action = FileParser._parse_replace_action(action_content)
            elif action_type == 'create_file':
                action = FileParser._parse_create_action(action_content)
            elif action_type == 'remove_file':
                action = {'action': 'remove_file'}
            elif action_type == 'replace_file':
                action = FileParser._parse_replace_file_action(action_content)
            if action:
                actions.append(action)
        return actions

    @staticmethod
    def _parse_replace_action(content: str) -> Optional[Dict[str, Any]]:
        start_marker_match = re.search(
            r'\[aibuilder_start_marker\](.*?)\[/aibuilder_start_marker\]',
            content,
            re.DOTALL
        )
        end_marker_match = re.search(
            r'\[aibuilder_end_marker\](.*?)\[/aibuilder_end_marker\]',
            content,
            re.DOTALL
        )
        new_content_match = re.search(
            r'\[aibuilder_new_content_exclusive\](.*?)\[/aibuilder_new_content_exclusive\]',
            content,
            re.DOTALL
        )
        if start_marker_match and end_marker_match and new_content_match:
            return {
                'action': 'replace_between_markers_exclusive',
                'start_marker': start_marker_match.group(1).strip(),
                'end_marker': end_marker_match.group(1).strip(),
                'new_content': new_content_match.group(1).strip().split('\n')
            }
        return None

    @staticmethod
    def _parse_create_action(content: str) -> Optional[Dict[str, Any]]:
        file_content_match = re.search(
            r'\[aibuilder_file_content\](.*?)\[/aibuilder_file_content\]',
            content,
            re.DOTALL
        )
        if file_content_match:
            return {
                'action': 'create_file',
                'file_content': file_content_match.group(1).strip().split('\n')
            }
        return None

    @staticmethod
    def _parse_replace_file_action(content: str) -> Optional[Dict[str, Any]]:
        file_content_match = re.search(
            r'\[aibuilder_file_content\](.*?)\[/aibuilder_file_content\]',
            content,
            re.DOTALL
        )
        if file_content_match:
            return {
                'action': 'replace_file',
                'file_content': file_content_match.group(1).strip().split('\n')
            }
        return None

class FileModifier:
    @staticmethod
    def replace_between_markers_exclusive(
        lines: List[str],
        start_marker: str,
        end_marker: str,
        new_content: List[str]
    ) -> List[str]:
        text = "\n".join(lines)
        start_index = text.find(start_marker)
        if start_index == -1:
            logging.error(f"Start marker '{start_marker}' not found.")
            return lines
        end_of_start_marker = start_index + len(start_marker)
        end_index = text.find(end_marker, end_of_start_marker)
        if end_index == -1:
            logging.error(f"End marker '{end_marker}' not found.")
            return lines
        new_content_text = "\n".join(new_content)
        text = (
            text[:start_index]
            + new_content_text
            + text[end_index:]
        )
        return text.split("\n")

    @staticmethod
    def apply_modifications(instruction_file: str) -> None:
        changes = FileParser.parse_custom_format(
            FileLoader.load_instructions(instruction_file)
        )
        for change in changes:
            filepath = change['file']
            logging.info(f"Processing file: {filepath}")
            if not os.path.isfile(filepath):
                logging.warning(f"File not found, creating: {filepath}")
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write("")
            for action in change['actions']:
                try:
                    FileModifier._apply_action(filepath, action)
                except Exception as e:
                    logging.error(f"Error applying modifications to {filepath}: {e}")

    @staticmethod
    def _apply_action(filepath: str, action: Dict[str, Any]) -> None:
        action_type = action['action']
        if action_type == 'replace_between_markers_exclusive':
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.read().splitlines()
            lines = FileModifier.replace_between_markers_exclusive(
                lines,
                action['start_marker'],
                action['end_marker'],
                action['new_content']
            )
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("\n".join(lines) + "\n")
            logging.info(f"Updated: {filepath}")
        elif action_type == 'create_file':
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("\n".join(action['file_content']) + "\n")
            logging.info(f"Created: {filepath}")
        elif action_type == 'remove_file':
            if os.path.isfile(filepath):
                os.remove(filepath)
                logging.info(f"Removed: {filepath}")
            else:
                logging.warning(f"File not found: {filepath}")
        elif action_type == 'replace_file':
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("\n".join(action['file_content']) + "\n")
            logging.info(f"Replaced entire content of: {filepath}")

class FileLoader:
    @staticmethod
    def load_instructions(format_path: str) -> str:
        try:
            with open(format_path, 'r', encoding='utf-8') as f:
                content = f.read()
            if "</think>" in content:
                content = content.split('</think>')[1]
            with open("ai_builder/extracted.txt", 'w', encoding='utf-8') as f:
                f.write(content)
            return content
        except Exception as e:
            logging.error(f"Error loading instructions: {e}")
            return ""

class CodeUtility:
    def __init__(self, base_dir: str = os.getcwd()):
        self.base_dir = base_dir
        self.output_file = os.path.join(base_dir, "ai_builder", "output.txt")
        self.log_file = os.path.join(base_dir, "ai_builder", "utility.log")

    def parse_gitignore(self, directory: str) -> List[str]:
        gitignore_path = os.path.join(directory, ".gitignore")
        if os.path.exists(gitignore_path):
            with open(gitignore_path, 'r', encoding='utf-8') as file:
                return [line.strip() for line in file if line.strip() and not line.strip().startswith('#')]
        return []

    def should_process_file(self, path: str, rules: List[str], patterns: List[str], mode: str) -> bool:
        file_name = os.path.basename(path)
        for rule in rules:
            if rule in path:
                return False
        for pattern in patterns:
            if pattern in file_name or pattern in path:
                return mode == "include"
        return mode == "exclude"

    def process_directory(self, directory: str, parent_rules: List[str], patterns: List[str], mode: str) -> None:
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

class AIBuilder:
    def __init__(self):
        self.return_git_diff = True

    def run_pre_post_scripts(self, script_name: str) -> None:
        script_path = os.path.join(os.getcwd(), script_name)
        if os.path.exists(script_path):
            try:
                subprocess.run(["powershell", "-File", script_path], check=True)
                logging.info(f"Successfully executed {script_name}")
            except subprocess.CalledProcessError as e:
                logging.error(f"Failed to execute {script_name}: {e}")

    def run(self) -> None:
        base_config_path = os.path.join("base_config.xml")
        user_config_path = os.path.join(ai_builder_dir, "user_config.xml")
        if os.path.exists(base_config_path):
            shutil.copy(base_config_path, user_config_path)
            logging.info("Copied base_config.xml to user_config.xml")
        else:
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

        os.chdir(root_directory)
        logging.info(f"Changed working directory to: {root_directory}")
        self.utility = CodeUtility(root_directory)
        config = ET.parse(user_config_path).getroot()
        iterations = int(config.find('iterations').text)
        mode = config.find('mode').text
        patterns = [pattern.text for pattern in config.findall('patterns/pattern')]

        for iteration in range(iterations):
            logging.info(f"Starting iteration {iteration + 1}")
            self.run_pre_post_scripts("pre.ps1")
            try:
                modifications_format_path = os.path.join(ai_builder_dir, "modifications.txt")
                if not os.path.exists(modifications_format_path):
                    if os.path.exists(self.utility.output_file):
                        os.remove(self.utility.output_file)
                    self.utility.process_directory(root_directory, [], patterns, mode)
                    if not os.path.exists(self.utility.output_file):
                        logging.warning("output.txt was not created by process_directory.")
                        continue
                    with open(self.utility.output_file, 'r', encoding='utf-8') as file:
                        current_code = file.read().strip()
                    logging.info("Successfully read output.txt")
                    with open('instructions.txt', 'r', encoding='utf-8') as file:
                        instructions = file.read().strip()
                    logging.info("Successfully read instructions.txt")

                    prompt = f"""
                        Generate a line-delimited format file that describes file modifications to apply using the `replace_between_markers_exclusive`, `create_file`, `remove_file`, and `replace_file` action types.
                        Ensure all content is provided using line-delimited format-compatible entities.
                        1. `replace_between_markers_exclusive`:
                            - `start_marker`: String
                            - `end_marker`: String
                            - `new_content`: List of strings (lines of replacement code/text)
                            Ensure that `new_content` DOES NOT include the `start_marker` and `end_marker` lines.
                            Ensure that `new_content` includes ALL necessary code that should be present between the `start_marker` and `end_marker` lines.
                            Include ONLY three lines of context before and after the new content to be included.
                            Ensure that each change is granular, representing no more than 20 lines of code
                        2. `create_file`:
                            - `file_content`: List of strings (lines of the file content)
                        3. `remove_file`:
                            - No additional parameters needed.
                        4. `replace_file`:
                            - `file_content`: List of strings (lines of the new file content)
                        Example output format:
                        ```
                        [aibuilder_change file="example.py"]
                        [aibuilder_action type="replace_between_markers_exclusive"]
                        [aibuilder_start_marker]
                        # Context line 1 before the change with whitespace preserved
                        \t# Context line 2 before the change with whitespace preserved
                        \t# Context line 3 before the change with whitespace preserved
                        [/aibuilder_start_marker]
                        [aibuilder_end_marker]
                        # Context line 1 after the change with whitespace preserved
                        \t# Context line 2 after the change with whitespace preserved
                        \t# Context line 3 after the change with whitespace preserved
                        [/aibuilder_end_marker]
                        [aibuilder_new_content_exclusive]
                        # Context line 1 before the change with whitespace preserved
                        \t# Context line 2 before the change with whitespace preserved
                        \t# Context line 3 before the change with whitespace preserved
                        # Modified line 1 with whitespace preserved
                        \t# Modified line 2 with whitespace preserved
                        # Context line 1 after the change with whitespace preserved
                        \t# Context line 2 after the change with whitespace preserved
                        \t# Context line 3 after the change with whitespace preserved
                        [/aibuilder_new_content_exclusive]
                        [/aibuilder_action]
                        [/aibuilder_change]
                        [aibuilder_change file="new_file.py"]
                        [aibuilder_action type="create_file"]
                        [aibuilder_file_content]
                        # Content line 1 with whitespace preserved
                        \t# Content line 2 with whitespace preserved
                        \t# Content line 3 with whitespace preserved
                        [/aibuilder_file_content]
                        [/aibuilder_action]
                        [/aibuilder_change]
                        [aibuilder_change file="old_file.py"]
                        [aibuilder_action type="remove_file"]
                        [/aibuilder_action]
                        [/aibuilder_change]
                        [aibuilder_change file="file_to_replace.py"]
                        [aibuilder_action type="replace_file"]
                        [aibuilder_file_content]
                        # New content line 1 with whitespace preserved
                        \t# New content line 2 with whitespace preserved
                        \t# New content line 3 with whitespace preserved
                        [/aibuilder_file_content]
                        [/aibuilder_action]
                        [/aibuilder_change]
                        ```
                        Generate modifications logically based on the desired changes.
                        Current code:
                        {current_code}
                        Instructions:
                        {instructions}
                        """
                    use_local_model = os.getenv("USE_LOCAL_MODEL", "false").lower() == "true"
                    if use_local_model:
                        model_path = os.getenv("MODEL_PATH")
                        if not model_path:
                            logging.error("MODEL_PATH environment variable not set for local model.")
                            raise ValueError("MODEL_PATH environment variable not set.")
                        llm = Llama(model_path=model_path, n_ctx=int(os.getenv("MODEL_CONTEXT", 0)))
                        response_content = ""
                        for response in llm.create_completion(
                            prompt,
                            max_tokens=int(os.getenv("MODEL_CONTEXT", 0))/2,
                            stream=True
                        ):
                            token = response['choices'][0]['text']
                            response_content += token
                    else:
                        endpoint = os.getenv("ENDPOINT")
                        model_name = os.getenv("MODEL_NAME")
                        api_key = os.getenv("API_KEY")
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
                            max_tokens=131072/2,
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
                if os.getenv("GENERATE_BUT_DO_NOT_APPLY", "false").lower() == "false":
                    FileModifier.apply_modifications(modifications_format_path)
            except Exception as e:
                logging.error(f"An error occurred: {str(e)}", exc_info=True)
            self.run_pre_post_scripts("post.ps1")

if __name__ == "__main__":
    ai_builder = AIBuilder()
    ai_builder.run()
