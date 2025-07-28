# AI Builder

AI Builder is a sophisticated tool designed to automate code modifications based on predefined instructions. It processes directories, applies changes to files, and can utilize either a local or cloud-based language model to generate modifications. The tool is highly configurable and provides extensive logging to track changes and errors.

## Features

- **Directory Processing**: Process directories and apply changes to files based on specified patterns.
- **Environment Configuration**: Use environment variables to configure behavior and settings.
- **Model Flexibility**: Optionally use a local language model or connect to a cloud-based model for generating modifications.
- **Comprehensive Logging**: Detailed logging for tracking changes, errors, and execution flow.
- **Backup and Restore**: Automatic backup of files before modifications with the ability to restore in case of errors.
- **Pre and Post Scripts**: Execute custom PowerShell scripts before and after processing.
- **Configuration Management**: Use XML-based configuration files for easy setup and customization.
- **Dry Run Mode**: Option to generate changes without applying them, useful for testing and validation.

## Installation

1. **Clone the Repository**:
   ```sh
   git clone <repository-url>
   cd ai-builder
   ```

2. **Install Dependencies**:
   ```sh
   pip install -r requirements.txt
   ```

3. **Set Up Environment Variables**:
   Create a `.env` file in the root directory and set the necessary environment variables:
   ```env
   ROOT_DIRECTORY=path/to/your/project
   USE_LOCAL_MODEL=true
   MODEL_PATH=path/to/your/local/model
   ENDPOINT=your_azure_endpoint
   MODEL_NAME=your_model_name
   MODEL_CONTEXT=max model context
   API_KEY=your_api_key
   GENERATE_BUT_DO_NOT_APPLY=false
   ```

## Usage

1. **Run the AI Builder**:
   ```sh
   python ai_builder.py
   ```

   The tool will process the directories and apply the necessary changes based on the instructions provided in the `instructions.txt` file.

2. **Configuration**:
   The tool uses a `user_config.xml` file for configuration. You can provide a `base_config.xml` file, which will be copied to `user_config.xml` if it exists. Otherwise, a default configuration will be created.

   Example `base_config.xml`:
   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
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
   </config>
   ```

3. **Pre and Post Scripts**:
   Ensure you have `pre.ps1` and `post.ps1` scripts in the root directory for any pre-processing or post-processing tasks.

4. **Instructions File**:
   Provide an `instructions.txt` file with the desired modifications and instructions for the AI Builder.

## Environment Variables

- `ROOT_DIRECTORY`: The root directory to process. Defaults to the current directory.
- `USE_LOCAL_MODEL`: Set to `true` to use a local language model. Defaults to `false`.
- `MODEL_PATH`: The path to the local language model.
- `ENDPOINT`: The Azure endpoint for the language model.
- `MODEL_NAME`: The name of the Azure language model.
- `MODEL_CONTEXT`: The context size for your local LLM.
- `API_KEY`: The API key for the Azure language model.
- `GENERATE_BUT_DO_NOT_APPLY`: Whether to only produce the changes and not apply them.

## Logging

The tool logs its activities to a `utility.log` file in the `ai_builder` directory. You can check this file for details on the changes applied and any errors encountered.

## License

This project is licensed under the MIT License.