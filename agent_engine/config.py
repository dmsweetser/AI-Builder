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
    def get_custom_endpoint_url() -> Optional[str]:
        return os.getenv("CUSTOM_ENDPOINT_URL")

    @staticmethod
    def get_custom_api_key() -> Optional[str]:
        return os.getenv("CUSTOM_API_KEY")

    @staticmethod
    def get_custom_model_name() -> Optional[str]:
        return os.getenv("CUSTOM_MODEL_NAME")

    @staticmethod
    def get_custom_verify_ssl() -> bool:
        return os.getenv("CUSTOM_VERIFY_SSL", "false").lower() == "true"

    @staticmethod
    def get_custom_max_tokens() -> int:
        return int(os.getenv("CUSTOM_MAX_TOKENS", "8192"))

    @staticmethod
    def get_timeout() -> int:
        return int(os.getenv("CUSTOM_TIMEOUT", "300"))

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
    def get_live_instruction(job_id: str, base_dir: Optional[str] = None) -> Optional[str]:
        """Read a live instruction file for a running job.

        If *base_dir* is given, look there (used by the UI which manages
        the shared ``aib_instance`` directory).  Otherwise fall back to the
        legacy ``agent_engine/aib_instance/`` path.
        """
        if base_dir:
            instruction_file = os.path.join(
                base_dir, "live_instruction.txt"
            )
        else:
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