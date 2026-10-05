"""Runtime configuration for the agentic engine."""

import os
import json
from typing import Optional


class EngineConfig:
    """Runtime configuration for the agentic engine."""

    @staticmethod
    def get_root_directory() -> str:
        return os.getenv("AIB_ROOT", os.getenv("ROOT_DIRECTORY", os.getcwd()))

    @staticmethod
    def get_ai_builder_dir(root_dir: str) -> str:
        return os.path.join(root_dir, "aib_instance", "output")

    @staticmethod
    def get_log_file_path(root_dir: str) -> str:
        return os.path.join(root_dir, "aib_instance", "output", "utility.log")

    @staticmethod
    def get_endpoint() -> Optional[str]:
        return os.getenv("ENDPOINT")

    @staticmethod
    def get_model_name() -> Optional[str]:
        return os.getenv("MODEL_NAME")

    @staticmethod
    def get_api_key() -> Optional[str]:
        return os.getenv("API_KEY")

    @staticmethod
    def use_local_model() -> bool:
        return os.getenv("USE_LOCAL_MODEL", "false").lower() == "true"

    @staticmethod
    def get_model_path() -> Optional[str]:
        return os.getenv("MODEL_PATH")

    @staticmethod
    def get_llama_binary_path() -> Optional[str]:
        return os.getenv("LLAMA_BINARY_PATH")

    @staticmethod
    def get_temperature() -> float:
        return float(os.getenv("TEMPERATURE", "0.1"))

    @staticmethod
    def get_top_p() -> float:
        return float(os.getenv("TOP_P", "0.9"))

    @staticmethod
    def get_top_k() -> int:
        return int(os.getenv("TOP_K", "40"))

    @staticmethod
    def get_min_p() -> float:
        return float(os.getenv("MIN_P", "0.0"))

    @staticmethod
    def get_output_tokens() -> int:
        return int(os.getenv("OUTPUT_TOKENS", "8192"))

    @staticmethod
    def get_model_context() -> int:
        return int(os.getenv("MODEL_CONTEXT", "128000"))

    @staticmethod
    def get_max_steps() -> int:
        return int(os.getenv("AIB_MAX_STEPS", "50"))

    @staticmethod
    def get_jd_cli_path() -> Optional[str]:
        return os.getenv("JD_CLI_PATH")

    @staticmethod
    def get_java_home() -> Optional[str]:
        return os.getenv("JAVA_HOME")

    @staticmethod
    def verify_ssl() -> bool:
        return os.getenv("VERIFY_SSL", "false").lower() == "true"

    @staticmethod
    def generate_but_do_not_apply() -> bool:
        return os.getenv("GENERATE_BUT_DO_NOT_APPLY", "false").lower() == "true"

    @staticmethod
    def get_pre_script() -> str:
        return os.getenv("AIB_PRE_SCRIPT", "")

    @staticmethod
    def get_post_script() -> str:
        return os.getenv("AIB_POST_SCRIPT", "")

    @staticmethod
    def get_dotnet_cli_path() -> Optional[str]:
        return os.getenv("DOTNET_CLI_PATH")

    @staticmethod
    def get_enabled_tools() -> Optional[list]:
        """Return a list of enabled tool names, or None for all tools."""
        tools_str = os.getenv("AIB_ENABLED_TOOLS")
        if tools_str:
            try:
                return json.loads(tools_str)
            except Exception:
                return None
        return None

    @staticmethod
    def get_live_instruction(job_id: str) -> Optional[str]:
        """Read a live instruction file for a running job."""
        instruction_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "aib_instance", "output", job_id, "live_instruction.txt"
        )
        if os.path.exists(instruction_file):
            try:
                with open(instruction_file, 'r') as f:
                    instruction = f.read().strip()
                # Clear the file after reading
                with open(instruction_file, 'w') as f:
                    f.write('')
                return instruction if instruction else None
            except Exception:
                return None
        return None

    @staticmethod
    def use_custom_endpoint() -> bool:
        """Returns whether to use a custom OpenAI-compatible endpoint."""
        return os.getenv("USE_CUSTOM_ENDPOINT", "false").lower() == "true"

    @staticmethod
    def get_custom_endpoint_url() -> Optional[str]:
        """Returns the custom endpoint URL."""
        return os.getenv("CUSTOM_ENDPOINT_URL")

    @staticmethod
    def get_custom_api_key() -> Optional[str]:
        """Returns the API key for the custom endpoint."""
        return os.getenv("CUSTOM_API_KEY")

    @staticmethod
    def get_custom_model_name() -> Optional[str]:
        """Returns the model name for the custom endpoint."""
        return os.getenv("CUSTOM_MODEL_NAME")

    @staticmethod
    def get_custom_api_version() -> str:
        """Returns the API version for the custom endpoint (default: v1)."""
        return os.getenv("CUSTOM_API_VERSION", "v1")

    @staticmethod
    def get_custom_verify_ssl() -> bool:
        """Returns whether to verify SSL for the custom endpoint."""
        return os.getenv("CUSTOM_VERIFY_SSL", "false").lower() == "true"

    @staticmethod
    def get_custom_max_tokens() -> int:
        """Returns max tokens for the custom endpoint."""
        return int(os.getenv("CUSTOM_MAX_TOKENS", "8192"))
