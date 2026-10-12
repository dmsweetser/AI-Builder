"""Centralized configuration class for environment variables and defaults.

This module is a thin re-export of EngineConfig from agent_engine.config
for backward compatibility. New code should import directly from
agent_engine.config.
"""

from agent_engine.config import EngineConfig as Config  # noqa: F401

# Re-export all public symbols for backward compatibility
__all__ = ["Config"]