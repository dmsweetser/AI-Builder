import os
import logging
import subprocess
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ai_builder.log'),
        logging.StreamHandler()
    ]
)

# Load the root directory from an environment variable
root_directory = os.getenv("ROOT_DIRECTORY")
if root_directory:
    os.chdir(root_directory)
    logging.info(f"Changed working directory to: {root_directory}")
else:
    logging.warning("ROOT_DIRECTORY environment variable not set, using current directory.")

try:
    # Read content from output.txt
    with open('output.txt', 'r') as file:
        current_code = file.read().strip()
    logging.info("Successfully read output.txt")

    # Read content from instructions.txt
    with open('instructions.txt', 'r') as file:
        instructions = file.read().strip()
    logging.info("Successfully read instructions.txt")

    # Retrieve the endpoint, model name, and API key from the environment variables
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
            UserMessage(content=f"""
I have the following code:
{current_code}
RESPOND ONLY WITH a properly formatted git diff output that does the following:
{instructions}
"""),
        ],
        max_tokens=131072/2,
        model=model_name
    )

    response_content = ""

    for update in response:
        if update.choices:
            response_content += update.choices[0].delta.content or ""

    logging.info("Successfully obtained response from client.")

    # Cut off the response prior to the text "</think>"
    if "</think>" in response_content:
        response_content = response_content.split("</think>")[0]

    # Write the response content to a patch file
    patch_file_path = 'changes.patch'
    with open(patch_file_path, 'w') as patch_file:
        patch_file.write(response_content)
    logging.info(f"Successfully wrote patch file to {patch_file_path}")

    # Apply the git diff using the patch command
    try:
        result = subprocess.run(
            f'git apply {patch_file_path}',
            shell=True,
            check=True,
            text=True,
            capture_output=True
        )
        logging.info("Git diff applied successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to apply git diff: {e.output}")

except Exception as e:
    logging.error(f"An error occurred: {str(e)}", exc_info=True)
