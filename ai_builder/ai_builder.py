import os
import logging
import subprocess
import re
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

return_git_diff = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ai_builder.log'),
        logging.StreamHandler()
    ]
)

def split_patch_file():
    with open('changes.patch', 'r') as file:
        content = file.read()

    # Split the content into separate patches
    patches = content.split('diff --git')
    for i, patch in enumerate(patches):
        if i == 0:
            continue  # Skip the first element as it's likely empty or not a patch
        with open(f'patch_{i}.patch', 'w') as patch_file:
            patch_file.write(f"diff --git{patch}")

def split_and_apply_patches():
    # First, split the main patch file
    split_patch_file()

    # Process each patch file
    patch_files = [f for f in os.listdir('.') if f.startswith('patch_') and f.endswith('.patch')]

    for patch_file in patch_files:
        print(f"Processing {patch_file}")

        # Split into hunks
        with open(patch_file, 'r') as f:
            content = f.read()

        # Find hunks (sections starting with @@)
        hunks = re.split(r'(^@@.*?@@.*?$)', content, flags=re.MULTILINE)

        if len(hunks) > 1:
            header = hunks[0]  # diff header
            success_count = 0

            for i in range(1, len(hunks), 2):
                if i + 1 < len(hunks):
                    hunk_content = header + hunks[i] + hunks[i + 1]
                    hunk_file = f"hunk_{i//2 + 1}.patch"

                    with open(hunk_file, 'w') as f:
                        f.write(hunk_content)

                    # Try to apply the hunk
                    result = subprocess.run(['git', 'apply', hunk_file],
                                          capture_output=True, text=True)

                    if result.returncode == 0:
                        print(f"  ✓ Applied {hunk_file}")
                        os.remove(hunk_file)
                        success_count += 1
                    else:
                        print(f"  ✗ Failed {hunk_file}: {result.stderr.strip()}")

            # Remove original patch if all hunks succeeded
            if success_count == (len(hunks) - 1) // 2:
                os.remove(patch_file)
                print(f"  All hunks applied successfully for {patch_file}")
        else:
            # Single hunk, try to apply directly
            result = subprocess.run(['git', 'apply', patch_file],
                                  capture_output=True, text=True)
            if result.returncode == 0:
                print(f"  ✓ Applied {patch_file}")
                os.remove(patch_file)
            else:
                print(f"  ✗ Failed {patch_file}: {result.stderr.strip()}")

# Load the root directory from an environment variable
root_directory = os.getenv("ROOT_DIRECTORY")
if root_directory:
    os.chdir(root_directory)
    logging.info(f"Changed working directory to: {root_directory}")
else:
    logging.warning("ROOT_DIRECTORY environment variable not set, using current directory.")

try:
    if not os.path.exists('changes.patch'):
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

        if return_git_diff:
            output_instruction =  "RESPOND ONLY WITH a properly formatted git diff output that does the following:"
        else:
            output_instruction =  "RESPOND WITH COMPLETE REVISIONS OF ALL IMPACTED FILES that addresses the following:"


        response = client.complete(
            stream=True,
            messages=[
                SystemMessage(content="You are a helpful assistant."),
                UserMessage(content=f"""
I have the following code:
{current_code}
{output_instruction}
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

        full_response_file = "full_response.txt"
        with open(full_response_file, 'w') as full_response_file:
            full_response_file.write(response_content)

        # Cut off the response prior to the text "</think>"
        if "</think>" in response_content:
            response_content = response_content.split("</think>")[1]

        # Write the response content to a patch file
        patch_file_path = 'changes.patch'
        with open(patch_file_path, 'w') as patch_file:
            patch_file.write(response_content)

        logging.info(f"Successfully wrote patch file to {patch_file_path}")

    # Apply the git diff using the patch command
    try:
        split_and_apply_patches()
        logging.info("Git diff applied successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to apply git diff: {e.output}")

except Exception as e:
    logging.error(f"An error occurred: {str(e)}", exc_info=True)
