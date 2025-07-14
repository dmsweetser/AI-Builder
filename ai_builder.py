import os
import logging
from dotenv import load_dotenv
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential
from code_utility import CodeUtility
import subprocess

# Load environment variables from .env file
load_dotenv()

class AIBuilder:
    def __init__(self):
        self.return_git_diff = True

    def run(self):
        root_directory = os.getenv("ROOT_DIRECTORY")
        self.utility = CodeUtility(root_directory)
        if root_directory:
            os.chdir(root_directory)
            logging.info(f"Changed working directory to: {root_directory}")
        else:
            logging.warning("ROOT_DIRECTORY environment variable not set, using current directory.")

        try:
            if not os.path.exists('changes.patch'):
                patterns = [
                    "package-lock.json",
                    "output.txt",
                    "full_request.txt",
                    "full_response.txt",
                    "instructions.txt",
                    "changes.patch",
                    ".git",
                    "utility.log"
                ]
                mode = "exclude"
                if os.path.exists(self.utility.output_file):
                    os.remove(self.utility.output_file)
                self.utility.process_directory(root_directory, [], patterns, mode)
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

                if self.return_git_diff:
                    output_instruction = "RESPOND ONLY WITH a properly formatted git diff output that does the following:"
                else:
                    output_instruction = "RESPOND WITH COMPLETE REVISIONS OF ALL IMPACTED FILES that addresses the following:"

                user_instruction = f"I have the following code:\n{current_code}\n{output_instruction}\n{instructions}"
                with open("full_request.txt", 'w', encoding='utf-8') as full_request_file:
                    full_request_file.write(user_instruction)

                response = client.complete(
                    stream=True,
                    messages=[
                        SystemMessage(content="You are a helpful assistant."),
                        UserMessage(content=user_instruction)
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
                with open("full_response.txt", 'w', encoding='utf-8') as full_response_file:
                    full_response_file.write(response_content)

                if "</think>" in response_content:
                    response_content = response_content.split("</think>")[1]

                with open('changes.patch', 'w', encoding='utf-8') as patch_file:
                    patch_file.write(response_content)
                logging.info("Successfully wrote patch file to changes.patch")

            try:
                self.utility.split_and_apply_patches('changes.patch')
                logging.info("Git diff applied successfully.")
            except subprocess.CalledProcessError as e:
                logging.error(f"Failed to apply git diff: {e.output}")

        except Exception as e:
            logging.error(f"An error occurred: {str(e)}", exc_info=True)

if __name__ == "__main__":
    ai_builder = AIBuilder()
    ai_builder.run()
