"""Runtime configuration for the agentic engine."""

import os
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
