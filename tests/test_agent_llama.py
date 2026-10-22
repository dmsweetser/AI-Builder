#!/usr/bin/env python3
"""Test the agent engine with llama-server."""

import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Configure the engine
os.environ["CUSTOM_ENDPOINT_URL"] = "http://localhost:8080/v1/chat/completions"
os.environ["CUSTOM_MODEL_NAME"] = "qwen35b"
os.environ["AIB_MAX_STEPS"] = "5"
os.environ["AIB_MAX_TOOL_RESULT_LENGTH"] = "4000"
os.environ["AIB_MAX_CONTEXT_TOKENS"] = "0"
os.environ["AIB_MAX_OUTPUT_TOKENS"] = "1024"

from agent_engine.engine import AgentEngine, parse_tool_calls, is_done

# Create a minimal config
config = {
    "rootDirectory": "/tmp/aibuilder_sample_project",
    "instructions": "List the files in the project root directory using list_directory.",
    "job_id": "test_" + str(int(time.time() * 1000)),
    "enabled_tools": ["list_directory", "search_files", "grep_code", "read_file", "write_file", "edit_file", "delete_file"]
}

# Create output dir
output_dir = "/tmp/aibuilder_test_output"
os.makedirs(output_dir, exist_ok=True)

# Create engine
events = []
def on_event(ev):
    events.append(ev)

engine = AgentEngine(config, output_dir=output_dir, step_callback=on_event)

# Run one step to test
print("Running agent step 1...")
response = engine.llm.call(engine.messages, system_prompt=engine.system_prompt)
print(f"Response (first 500 chars): {response[:500]}")
print(f"Response length: {len(response)}")

# Check for tool calls
tool_calls = parse_tool_calls(response)
print(f"Tool calls found: {len(tool_calls)}")
for name, params in tool_calls:
    print(f"  Tool: {name}, Params: {params}")

# Check for DONE
done, summary = is_done(response)
print(f"Done: {done}, Summary: {summary[:100] if summary else ''}")
