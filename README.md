
# AI Builder

AI Builder is a sophisticated tool designed to automate code modifications based on predefined instructions. It features a modern web UI for project management, visual file tree selection, and integrated AI chat. The tool processes directories, applies changes to files, and can utilize either a local or cloud-based language model to generate modifications.

## Features

- **Web UI Interface**: Manage projects, select files visually, and configure AI instructions through a responsive dashboard.
- **Environment Configuration**: Use environment variables to configure model endpoints, paths, and execution behavior.
- **Model Flexibility**: Seamlessly switch between local GGUF models or cloud-based Azure AI Foundry endpoints.
- **Integrated Chat**: Built-in AI chat interface for iterative prompt refinement and debugging.
- **Comprehensive Logging**: Detailed logging for tracking changes, errors, and execution flow.
- **Backup and Restore**: Automatic backup of files before modifications with the ability to restore in case of errors.
- **Pre and Post Scripts**: Execute custom PowerShell scripts before and after processing.
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

1. **Start the Web UI**:
   ```sh
   python ui.py
   ```
   Open your browser and navigate to `http://localhost:5000`.

2. **Create a Project**:
   - Enter a project name and root directory.
   - Click **LOAD TREE** to browse and select files/folders.
   - Use **SELECT ALL** / **DESELECT ALL** to quickly toggle selections.
   - Provide AI instructions, pre/post scripts, and iteration settings.
   - Click **CREATE PROJECT**.

3. **Run AI Builder**:
   - Select your project from the dashboard.
   - Review or modify instructions and scripts.
   - Click **RUN AI BUILDER** to execute the automation pipeline.
   - Monitor progress and view logs directly in the UI.

4. **Configuration**:
   Project settings are stored in `aib_instance/projects.json`. The tool automatically reads `base_config.xml` if present, but all core behavior is now managed through the UI and `.env` file.

   Example `base_config.xml` (optional fallback):
   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <config>
       <iterations>1</iterations>
       <mode>exclude</mode>
       <git_diff_command>git diff --name-only</git_diff_command>
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

5. **Pre and Post Scripts**:
   Ensure you have `pre.ps1` and `post.ps1` scripts in the root directory for any pre-processing or post-processing tasks. These can be configured per-project in the UI.

6. **Instructions File**:
   Instructions are now entered directly in the project details panel. The legacy `instructions.txt` file is no longer required for UI mode.


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