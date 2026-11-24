"""AI Builder - Agentic Multi-Step Engine Package."""

import threading as _threading
from agent_engine.engine import AgentEngine, run
from agent_engine.config import EngineConfig
from agent_engine.security import SecurityError, ToolError, EngineError
from agent_engine.tools import ToolRegistry, get_registry
from agent_engine.tools.base import ToolResult

__all__ = ["AgentEngine", "run", "EngineConfig", "SecurityError", "ToolError", "EngineError", "ToolRegistry", "ToolResult", "get_registry"]


def run_with_stop_event(project_config, output_dir=None, step_callback=None, stop_event=None):
    """Run the agentic engine with an optional stop event for interruption."""
    engine = AgentEngine(project_config, output_dir=output_dir,
                         step_callback=step_callback, stop_event=stop_event)
    try:
        return engine.run()
    finally:
        engine.close()
