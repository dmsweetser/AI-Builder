import os
import re
import logging
import shutil
import subprocess
import html
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

# Load environment variables from .env file
load_dotenv()

def translate_xml_entities(text):
    # Detect and translate XML entities if present
    if re.search(r'&(?:[a-z]+|#\d+|#x[a-fA-F0-9]+);', text):
        return html.unescape(text)
    return text

def extract_xml_content(text):
    start_marker = "```xml"
    end_marker = "```"
    start_index = text.find(start_marker)
    if start_index == -1:
        return text
    start_index = text.find('\n', start_index) + 1
    end_index = text.rfind(end_marker)
    if end_index == -1 or end_index <= start_index:
        return text
    xml_content = text[start_index:end_index].strip()
    return xml_content

def parse_custom_xml(xml_content):
    changes = []
    change_blocks = re.findall(r'<aibuilder_change file="([^"]+)">(.*?)</aibuilder_change>', xml_content, re.DOTALL)
    for file, actions in change_blocks:
        action_list = []
        action_blocks = re.findall(r'<aibuilder_action type="([^"]+)">(.*?)</aibuilder_action>', actions, re.DOTALL)
        for action_type, action_data in action_blocks:
            if action_type == 'replace_between_markers':
                start_marker = re.search(r'<aibuilder_start_marker>(.*?)</aibuilder_start_marker>', action_data).group(1)
                end_marker = re.search(r'<aibuilder_end_marker>(.*?)</aibuilder_end_marker>', action_data).group(1)
                new_content = re.search(r'<aibuilder_new_content>(.*?)</aibuilder_new_content>', action_data, re.DOTALL).group(1).strip()
                new_content = translate_xml_entities(new_content).split('\n')
                action_list.append({'action': action_type, 'start_marker': translate_xml_entities(start_marker), 'end_marker': translate_xml_entities(end_marker), 'new_content': new_content})
            elif action_type == 'replace_line_containing':
                match_substring = re.search(r'aibuilder_match_substring="([^"]+)"', action_data).group(1)
                replacement_line = re.search(r'aibuilder_replacement_line="([^"]+)"', action_data).group(1)
                action_list.append({'action': action_type, 'match_substring': translate_xml_entities(match_substring), 'replacement_line': translate_xml_entities(replacement_line)})
            elif action_type in ['append', 'prepend']:
                content = re.search(r'<aibuilder_content>(.*?)</aibuilder_content>', action_data, re.DOTALL).group(1).strip()
                content = translate_xml_entities(content).split('\n')
                action_list.append({'action': action_type, 'content': content})
            elif action_type == 'regex_replace':
                pattern = re.search(r'aibuilder_pattern="([^"]+)"', action_data).group(1)
                replacement = re.search(r'aibuilder_replacement="([^"]+)"', action_data).group(1)
                action_list.append({'action': action_type, 'pattern': translate_xml_entities(pattern), 'replacement': translate_xml_entities(replacement)})
        changes.append({'file': translate_xml_entities(file), 'actions': action_list})
    return changes

def load_instructions(xml_path):
    with open(xml_path, 'r', encoding='utf-8') as f:
        content = f.read()
    if "</think>" in content:
        content = content.split("</think>")[1]
    xml_content = extract_xml_content(content)
    with open("ai_builder/extracted.xml", 'w', encoding='utf-8') as f:
        f.write(xml_content)
    return parse_custom_xml(xml_content)

def replace_between_markers(lines, start_marker, end_marker, new_content):
    new_lines = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if start_marker in line:
            new_lines.extend(new_content)
            while i < n and end_marker not in lines[i]:
                i += 1
            if i < n:
                new_lines.append(lines[i])
        else:
            new_lines.append(line)
        i += 1
    return new_lines

def regex_replace(lines, pattern, replacement):
    compiled = re.compile(pattern)
    return [compiled.sub(replacement, line) for line in lines]

def replace_line_containing(lines, match_substring, replacement_line):
    return [replacement_line if match_substring in line else line for line in lines]

def apply_modifications(instruction_file):
    changes = load_instructions(instruction_file)
    for change in changes:
        filepath = change['file']
        if not os.path.isfile(filepath):
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("")
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
        for action in change['actions']:
            action_type = action['action']
            if action_type == 'replace_between_markers':
                lines = replace_between_markers(
                    lines,
                    action['start_marker'],
                    action['end_marker'],
                    action['new_content']
                )
            elif action_type == 'append':
                new_lines = [line for line in action['content'] if line not in lines]
                lines.extend(new_lines)
            elif action_type == 'prepend':
                new_lines = [line for line in action['content'] if line not in lines]
                lines = new_lines + lines
            elif action_type == 'regex_replace':
                lines = regex_replace(
                    lines,
                    action['pattern'],
                    action['replacement']
                )
            elif action_type == 'replace_line_containing':
                lines = replace_line_containing(
                    lines,
                    action['match_substring'],
                    action['replacement_line']
                )
            else:
                print(f"[WARNING] Unknown action type: {action_type}")
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines) + "\n")
        print(f"[INFO] Updated: {filepath}")

class CodeUtility:
    def __init__(self, base_dir: str = os.getcwd()):
        self.base_dir = base_dir
        self.output_file = os.path.join(base_dir, "ai_builder", "output.txt")
        self.log_file = os.path.join(base_dir, "ai_builder", "utility.log")
        self.setup_logging()

    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.log_file),
                logging.StreamHandler()
            ]
        )

    def parse_gitignore(self, directory: str):
        gitignore_path = os.path.join(directory, ".gitignore")
        if os.path.exists(gitignore_path):
            with open(gitignore_path, 'r') as file:
                return [line.strip() for line in file if line.strip() and not line.strip().startswith('#')]
        return []

    def should_process_file(self, path: str, rules: list, patterns: list, mode: str):
        file_name = os.path.basename(path)
        for rule in rules:
            if rule in path:
                return False
        for pattern in patterns:
            if pattern in file_name or pattern in path:
                return mode == "include"
        return mode == "exclude"

    def process_directory(self, directory: str, parent_rules: list, patterns: list, mode: str):
        current_rules = self.parse_gitignore(directory)
        all_rules = parent_rules + current_rules
        logging.info(f"Processing directory: {directory}")
        for root, dirs, files in os.walk(directory):
            logging.info(f"Current root: {root}, dirs: {dirs}, files: {files}")
            for file in files:
                relative_path = os.path.relpath(os.path.join(root, file), self.base_dir)
                logging.info(f"Checking file: {relative_path}")
                if self.should_process_file(relative_path, all_rules, patterns, mode):
                    try:
                        with open(os.path.join(root, file), 'r') as f:
                            content = f.read()
                        with open(self.output_file, 'a') as out_file:
                            out_file.write(f"\n### {relative_path}\n```\n{content}\n```\n")
                        logging.info(f"Successfully wrote content from {relative_path} to {self.output_file}")
                    except Exception as e:
                        logging.error(f"Skipped unreadable file: {relative_path} - Error: {e}")

class AIBuilder:
    def __init__(self):
        self.return_git_diff = True

    def run_pre_post_scripts(self, script_name):
        script_path = os.path.join(os.getcwd(), script_name)
        if os.path.exists(script_path):
            try:
                subprocess.run(["powershell", "-File", script_path], check=True)
                logging.info(f"Successfully executed {script_name}")
            except subprocess.CalledProcessError as e:
                logging.error(f"Failed to execute {script_name}: {e}")

    def run(self):
        root_directory = os.getenv("ROOT_DIRECTORY")
        if not root_directory:
            logging.warning("ROOT_DIRECTORY environment variable not set, using current directory.")
            root_directory = os.getcwd()
        ai_builder_dir = os.path.join(root_directory, "ai_builder")
        os.makedirs(ai_builder_dir, exist_ok=True)
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
            with open(user_config_path, 'w') as config_file:
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
                modifications_xml_path = os.path.join(ai_builder_dir, "modifications.xml")
                if not os.path.exists(modifications_xml_path):
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
                    prompt = f"""
                    Generate an XML file that describes file modifications to apply using the following supported action types.
                    Ensure all content is provided using XML-compatible entities.
                    1. `replace_between_markers`:
                        - `start_marker`: String
                        - `end_marker`: String
                        - `new_content`: List of strings (lines of replacement code/text)
                        Ensure that `new_content` includes the `start_marker` and `end_marker` lines if they should be part of the replacement.
                        Also ensure that unmodified code between the markers is faithfully preserved.
                    2. `append`:
                        - `content`: List of strings to append to end of file
                    3. `prepend`:
                        - `content`: List of strings to add to top of file
                    4. `regex_replace`:
                        - `pattern`: Regex pattern
                        - `replacement`: Replacement string
                    5. `replace_line_containing`:
                        - `match_substring`: Text to search for within lines
                        - `replacement_line`: Full line to replace matched lines with
                    Example output format:
                    ```xml
                    <aibuilder_changes>
                        <aibuilder_change file="example.py">
                            <aibuilder_action type="append">
                                <aibuilder_content># Automatically added comment.</aibuilder_content>
                            </aibuilder_action>
                        </aibuilder_change>
                    </aibuilder_changes>
                    ```
                    Ensure the XML is strictly valid. Generate modifications logically based on the desired changes.
                    Current code:
                    {current_code}
                    Instructions:
                    {instructions}
                    """
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
                    for update in response:
                        if update.choices and isinstance(update.choices, list) and len(update.choices) > 0:
                            content = update.choices[0].get("delta", {}).get("content", "")
                            if content is not None:
                                response_content += content
                        else:
                            logging.warning("Unexpected response format: choices list is empty or invalid.")
                    logging.info("Successfully obtained response from client.")
                    with open(modifications_xml_path, 'w', encoding='utf-8') as modifications_file:
                        modifications_file.write(response_content)
                    logging.info(f"Successfully wrote modifications file to {modifications_xml_path}")
                apply_modifications(modifications_xml_path)
            except Exception as e:
                logging.error(f"An error occurred: {str(e)}", exc_info=True)
            self.run_pre_post_scripts("post.ps1")

if __name__ == "__main__":
    ai_builder = AIBuilder()
    ai_builder.run()
