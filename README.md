# AI Builder

AI Builder is a tool designed to automate code modifications based on predefined instructions. It can process directories, apply changes to files, and optionally use a local language model for generating modifications.

## Features

- Process directories and apply changes to files based on patterns.
- Use environment variables to configure the behavior.
- Optionally use a local language model for generating modifications.
- Logging for tracking changes and errors.

## Installation

1. Clone the repository:

```sh
git clone <repository-url>
cd ai-builder
```

2. Install the required dependencies:

```sh
pip install -r requirements.txt
```

3. Create a .env file in the root directory and set the necessary environment variables:

```
ROOT_DIRECTORY=path/to/your/project
USE_LOCAL_MODEL=true
MODEL_PATH=path/to/your/local/model
ENDPOINT=your_azure_endpoint
MODEL_NAME=your_model_name
API_KEY=your_api_key
```

## Usage

1. Run the AI Builder:

```sh
python ai_builder.py
```

The tool will process the directories and apply the necessary changes based on the instructions provided in the instructions.txt file.

## Environment Variables

ROOT_DIRECTORY: The root directory to process. Defaults to the current directory.
USE_LOCAL_MODEL: Set to true to use a local language model. Defaults to false.
MODEL_PATH: The path to the local language model.
ENDPOINT: The Azure endpoint for the language model.
MODEL_NAME: The name of the Azure language model.
API_KEY: The API key for the Azure language model.

## Configuration

The tool uses a user_config.xml file for configuration. You can provide a base_config.xml file, which will be copied to user_config.xml if it exists. Otherwise, a default configuration will be created.

Example base_config.xml:

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

## Logging

The tool logs its activities to a utility.log file in the ai_builder directory. You can check this file for details on the changes applied and any errors encountered.

## License

This project is licensed under the MIT License.
