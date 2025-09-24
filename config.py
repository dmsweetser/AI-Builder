import os
from typing import Optional

class Config:
    """Centralized configuration class for environment variables and defaults."""

    @staticmethod
    def get_root_directory() -> str:
        """Returns the root directory, defaulting to the current working directory."""
        return os.getenv("ROOT_DIRECTORY", os.getcwd())

    @staticmethod
    def get_ai_builder_dir(root_dir: str) -> str:
        """Returns the path to the ai_builder directory."""
        return os.path.join(root_dir, "ai_builder")

    @staticmethod
    def use_local_model() -> bool:
        """Returns whether to use a local model."""
        return os.getenv("USE_LOCAL_MODEL", "false").lower() == "true"

    @staticmethod
    def get_model_path() -> Optional[str]:
        """Returns the path to the local model, if USE_LOCAL_MODEL is True."""
        return os.getenv("MODEL_PATH")

    @staticmethod
    def get_model_context() -> int:
        """Returns the context size for the local model."""
        return int(os.getenv("MODEL_CONTEXT", 0))

    @staticmethod
    def get_temperature() -> int:
        """Returns the temperature for the local model."""
        return float(os.getenv("TEMPERATURE", 1))

    @staticmethod
    def get_top_p() -> int:
        """Returns the top_p for the local model."""
        return float(os.getenv("TOP_P", 1))

    @staticmethod
    def get_output_tokens() -> int:
        """Returns the maximum number of output tokens."""
        return int(os.getenv("OUTPUT_TOKENS", 0))

    @staticmethod
    def get_endpoint() -> Optional[str]:
        """Returns the Azure endpoint for the remote model."""
        return os.getenv("ENDPOINT")

    @staticmethod
    def get_model_name() -> Optional[str]:
        """Returns the model name for the remote model."""
        return os.getenv("MODEL_NAME")

    @staticmethod
    def get_api_key() -> Optional[str]:
        """Returns the API key for the remote model."""
        return os.getenv("API_KEY")

    @staticmethod
    def generate_but_do_not_apply() -> bool:
        """Returns whether to generate changes but not apply them."""
        return os.getenv("GENERATE_BUT_DO_NOT_APPLY", "false").lower() == "true"
    
    @staticmethod
    def generate_output_only() -> Optional[str]:
        """Returns whether to only generate the target code output and nothing more."""
        return os.getenv("GENERATE_OUTPUT_ONLY", False)

    @staticmethod
    def get_log_file_path(root_dir: str) -> str:
        """Returns the path to the log file."""
        return os.path.join(root_dir, "ai_builder", "utility.log")

    @staticmethod
    def get_output_file_path(root_dir: str) -> str:
        """Returns the path to the output file."""
        return os.path.join(root_dir, "ai_builder", "output.txt")