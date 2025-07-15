import os
import json
import logging
import shutil
import subprocess
from dotenv import load_dotenv
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential
from code_utility import CodeUtility
from file_mod_engine import apply_modifications

# Load environment variables from .env file
load_dotenv()

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

        # Create ai_builder subdirectory
        ai_builder_dir = os.path.join(root_directory, "ai_builder")
        os.makedirs(ai_builder_dir, exist_ok=True)

        # Define paths for configuration files
        base_config_path = os.path.join("base_config.json")
        user_config_path = os.path.join(ai_builder_dir, "user_config.json")

        # Copy base_config.json to user_config.json or create a default configuration
        if os.path.exists(base_config_path):
            shutil.copy(base_config_path, user_config_path)
            logging.info("Copied base_config.json to user_config.json")
        else:
            # Create a default configuration
            default_config = {
                "iterations": 1,
                "mode": "exclude",
                "patterns": [
                    "package-lock.json",
                    "output.txt",
                    "full_request.txt",
                    "full_response.txt",
                    "instructions.txt",
                    "changes.patch",
                    ".git",
                    "utility.log",
                    ".png",
                    ".exe",
                    ".ico",
                    ".webp",
                    ".gguf"
                ]
            }
            with open(user_config_path, 'w') as config_file:
                json.dump(default_config, config_file)
            logging.warning("base_config.json not found, created default user_config.json")

        os.chdir(root_directory)
        logging.info(f"Changed working directory to: {root_directory}")

        # Initialize CodeUtility after ensuring the directory exists
        self.utility = CodeUtility(root_directory)

        with open(user_config_path, 'r') as config_file:
            config = json.load(config_file)
            iterations = config.get("iterations", 1)
            mode = config.get("mode", "exclude")
            patterns = config.get("patterns", [])

        for iteration in range(iterations):
            logging.info(f"Starting iteration {iteration + 1}")
            self.run_pre_post_scripts("pre.ps1")

            try:
                if not os.path.exists(os.path.join(ai_builder_dir, 'modifications.json')):
                    if os.path.exists(self.utility.output_file):
                        os.remove(self.utility.output_file)
                    self.utility.process_directory(root_directory, [], patterns, mode)

                    # Ensure output.txt is created and not empty
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
                    Generate a JSON file that describes file modifications to apply using the following supported action types:

                    1. `replace_between_markers`:
                        - `start_marker`: String
                        - `end_marker`: String
                        - `new_content`: List of strings (lines of replacement code/text)

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

                    ```json
                    {{
                        "changes": [
                            {{
                                "file": "example.py",
                                "actions": [
                                    {{
                                        "action": "append",
                                        "content": ["# Automatically added comment."]
                                    }}
                                ]
                            }}
                        ]
                    }}
                    ```

                    Ensure the JSON is strictly valid. Do not include comments in the JSON. Generate modifications logically based on the desired changes.

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
                        max_tokens=131072 // 2,
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

                    # Save the generated modifications.json file
                    modifications_json_path = os.path.join(ai_builder_dir, "modifications.json")
                    with open(modifications_json_path, 'w', encoding='utf-8') as modifications_file:
                        modifications_file.write(response_content)

                    logging.info(f"Successfully wrote modifications file to {modifications_json_path}")

                    # Validate the modifications.json file
                    try:
                        with open(modifications_json_path, 'r', encoding='utf-8') as modifications_file:
                            modifications = json.load(modifications_file)
                        if "changes" not in modifications:
                            raise ValueError("Invalid modifications.json file: 'changes' key not found.")
                        logging.info("Successfully validated modifications.json file.")
                    except json.JSONDecodeError as e:
                        logging.error(f"Failed to validate modifications.json file: {e}")
                        raise ValueError("Invalid modifications.json file.")

                # Apply the modifications
                apply_modifications(modifications_json_path)

            except Exception as e:
                logging.error(f"An error occurred: {str(e)}", exc_info=True)

            self.run_pre_post_scripts("post.ps1")

if __name__ == "__main__":
    ai_builder = AIBuilder()
    ai_builder.run()
