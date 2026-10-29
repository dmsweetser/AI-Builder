"""
Mock OpenAI-compatible LLM endpoint for testing AI Builder.

This server listens on a specified port and returns prescribed responses
based on the input messages. It supports streaming responses and tracks
conversation history for stateful testing.

Usage:
    python tests/mock_llm_server.py --port 12345
    
Then configure AI Builder to point to http://127.0.0.1:12345/v1/chat/completions
"""

import argparse
import json
import logging
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, List, Any, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MockLLMResponse:
    """A prescribed response for a given input pattern."""
    
    def __init__(self, pattern: str, response: str, 
                 tool_calls: Optional[List[MockLLMToolCall]] = None,
                 delay: float = 0.0, finish_reason: str = "stop",
                 sequential: bool = False):
        self.pattern = pattern  # Regex pattern to match against input
        self.response = response  # Text response (fallback if no tool_calls)
        self.tool_calls = tool_calls or []  # Tool calls to return
        self.delay = delay  # Simulated processing delay
        self.finish_reason = finish_reason  # "stop" or "tool_calls"
        self.sequential = sequential  # If True, use in order regardless of pattern


class MockLLMState:
    """Tracks state across the conversation."""
    
    def __init__(self):
        self.conversation_count = 0
        self.tool_call_count = 0
        self.pending_user_input_count = 0
        self.history: List[Dict] = []
    
    def reset(self):
        self.conversation_count = 0
        self.tool_call_count = 0
        self.pending_user_input_count = 0
        self.history = []


class MockLLMToolCall:
    """A tool call to return in the response."""
    
    def __init__(self, name: str, arguments: Dict[str, str]):
        self.name = name
        self.arguments = arguments


class MockLLMHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the mock LLM endpoint."""
    
    # Class-level state shared across all requests
    state: MockLLMState = MockLLMState()
    responses: List[MockLLMResponse] = []
    server_instance: Optional['MockLLMServer'] = None
    
    def log_message(self, format, *args):
        """Override to use our logger."""
        logger.info(f"[HTTP] {format % args}")
    
    def do_POST(self):
        """Handle POST requests to the chat completions endpoint."""
        if self.path != '/v1/chat/completions':
            self.send_error(404, "Not Found")
            return
        
        # Read the request body
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        
        try:
            request_data = json.loads(body.decode('utf-8'))
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return
        
        # Extract messages from the request
        messages = request_data.get('messages', [])
        stream = request_data.get('stream', False)
        
        # Find the last user message
        last_user_message = ""
        for msg in reversed(messages):
            if msg.get('role') == 'user':
                last_user_message = msg.get('content', '')
                break
        
        # Log the request
        logger.info(f"[MOCK] Received request with {len(messages)} messages")
        logger.info(f"[MOCK] Last user message: {last_user_message[:200]}...")
        
        # Add to history
        MockLLMHandler.state.history.extend(messages)
        
        # Simulate processing delay
        time.sleep(0.5)
        
        # Find a matching response
        response_text = "I'm a mock AI. I can't do much yet."
        tool_calls = []
        finish_reason = "stop"
        
        # First, check for sequential responses (used in order)
        sequential_responses = [r for r in MockLLMHandler.responses if r.sequential]
        if sequential_responses:
            # Use the next sequential response
            seq_response = sequential_responses[MockLLMHandler.state.conversation_count % len(sequential_responses)]
            response_text = seq_response.response
            tool_calls = seq_response.tool_calls
            finish_reason = seq_response.finish_reason
            MockLLMHandler.state.conversation_count += 1
        else:
            # Fall back to pattern matching
            for mock_response in MockLLMHandler.responses:
                import re
                if re.search(mock_response.pattern, last_user_message, re.IGNORECASE):
                    response_text = mock_response.response
                    tool_calls = mock_response.tool_calls
                    finish_reason = "tool_calls" if tool_calls else "stop"
                    break
        
        # Build the response
        if stream:
            self._send_streaming_response(response_text, tool_calls, finish_reason)
        else:
            self._send_non_streaming_response(response_text, tool_calls, finish_reason)
    
    def _send_streaming_response(self, response_text: str, tool_calls: List[Any], finish_reason: str):
        """Send a streaming response (SSE format)."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()
        
        # Send the initial chunk
        chunk_id = f"chatcmpl-{int(time.time() * 1000)}"
        
        if tool_calls:
            # Send content delta (empty for tool calls)
            for i, tc in enumerate(tool_calls):
                # Handle both dict and MockLLMToolCall formats
                if hasattr(tc, 'name'):
                    tc_name = tc.name
                    tc_args = tc.arguments
                else:
                    tc_name = tc["function"]["name"]
                    tc_args = tc["function"]["arguments"]
                
                # Send tool calls
                data = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "mock-llm",
                    "choices": [{
                        "index": 0,
                        "delta": {
                            "content": "",
                            "tool_calls": [{
                                "index": i,
                                "id": f"call_{i}",
                                "type": "function",
                                "function": {
                                    "name": tc_name,
                                    "arguments": json.dumps(tc_args)
                                }
                            }]
                        },
                        "finish_reason": None
                    }]
                }
                self.wfile.write(f"data: {json.dumps(data)}\n\n".encode('utf-8'))
                self.wfile.flush()
                time.sleep(0.1)
        else:
            # Send content in chunks, preserving newlines
            # Split by newlines first, then send each line as a chunk
            parts = response_text.split('\n')
            for i, part in enumerate(parts):
                data = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "mock-llm",
                    "choices": [{
                        "index": 0,
                        "delta": {"content": part},
                        "finish_reason": None
                    }]
                }
                self.wfile.write(f"data: {json.dumps(data)}\n\n".encode('utf-8'))
                self.wfile.flush()
                # Add newline between parts (except after the last one)
                if i < len(parts) - 1:
                    newline_data = {
                        "id": chunk_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": "mock-llm",
                        "choices": [{
                            "index": 0,
                            "delta": {"content": "\n"},
                            "finish_reason": None
                        }]
                    }
                    self.wfile.write(f"data: {json.dumps(newline_data)}\n\n".encode('utf-8'))
                    self.wfile.flush()
        
        # Send the final chunk with finish_reason
        data = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": "mock-llm",
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": finish_reason
            }]
        }
        self.wfile.write(f"data: {json.dumps(data)}\n\n".encode('utf-8'))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
    
    def _send_non_streaming_response(self, response_text: str, tool_calls: List[Any], finish_reason: str):
        """Send a non-streaming response."""
        # Build tool_calls in OpenAI format (handle both dict and MockLLMToolCall)
        openai_tool_calls = None
        if tool_calls:
            openai_tool_calls = []
            for i, tc in enumerate(tool_calls):
                if hasattr(tc, 'name'):
                    openai_tool_calls.append({
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)
                        }
                    })
                else:
                    openai_tool_calls.append(tc)
        
        response = {
            "id": f"chatcmpl-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "mock-llm",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response_text if not tool_calls else None,
                    "tool_calls": openai_tool_calls if openai_tool_calls else None
                },
                "finish_reason": finish_reason
            }],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150
            }
        }
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response).encode('utf-8'))


class MockLLMServer:
    """A mock LLM server that returns prescribed responses."""
    
    def __init__(self, host: str = '127.0.0.1', port: int = 0):
        self.host = host
        self.port = port
        self.server = None
        self.thread = None
    
    def start(self):
        """Start the mock LLM server."""
        self.server = HTTPServer((self.host, self.port), MockLLMHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        logger.info(f"[MOCK] Mock LLM server started on http://{self.host}:{self.port}")
        return self.port
    
    def stop(self):
        """Stop the mock LLM server."""
        if self.server:
            self.server.shutdown()
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=5)
            logger.info("[MOCK] Mock LLM server stopped")
    
    def add_response(self, pattern: str, response: str, 
                     tool_calls: Optional[List[Any]] = None,
                     delay: float = 0.0):
        """Add a prescribed response for a given input pattern.
        
        Args:
            pattern: Regex pattern to match against input
            response: Text response (fallback if no tool_calls)
            tool_calls: List of MockLLMToolCall objects OR dicts with
                        {"function": {"name": ..., "arguments": {...}}}
            delay: Simulated processing delay (default 0 for tests)
        """
        MockLLMHandler.responses.append(
            MockLLMResponse(pattern, response, tool_calls, delay)
        )
        logger.info(f"[MOCK] Added response for pattern: {pattern}")
    
    def add_tool_call_response(self, pattern: str, tool_name: str, 
                                arguments: Dict[str, str], delay: float = 0.0):
        """Add a response that returns a tool call in tag-based format.
        
        The engine's LLMClient parses the content string with parse_tool_calls(),
        so we return the tool call as a formatted string.
        """
        # Build the tag-based tool call string
        lines = ["[TOOL_START]", "[TOOL_NAME]", tool_name]
        for key, value in arguments.items():
            lines.extend(["[PARAM_NAME]", key, "[PARAM_VALUE]", value])
        lines.append("[TOOL_END]")
        response_text = "\n".join(lines)
        
        MockLLMHandler.responses.append(
            MockLLMResponse(pattern, response_text, [], delay, finish_reason="stop")
        )
        logger.info(f"[MOCK] Added tool call response for pattern: {pattern} -> {tool_name}")
    
    def add_sequential_response(self, response: str, 
                                 tool_calls: Optional[List[Any]] = None,
                                 delay: float = 0.0, finish_reason: str = "stop"):
        """Add a response that is used in sequential order, regardless of input pattern.
        
        This is useful for E2E tests where the LLM response depends on conversation
        history, not just the last message.
        """
        MockLLMHandler.responses.append(
            MockLLMResponse("", response, tool_calls, delay, finish_reason, sequential=True)
        )
        logger.info(f"[MOCK] Added sequential response (finish_reason={finish_reason})")
    
    def reset_state(self):
        """Reset the mock server state."""
        MockLLMState.state.reset()
        MockLLMHandler.responses.clear()
        logger.info("[MOCK] State reset")


def create_default_responses():
    """Create default responses for testing."""
    server = MockLLMServer()
    port = server.start()
    
    # Response 1: Initial list_directory call
    server.add_response(
        r"list_directory",
        "I'll help you with that. Let me explore the project structure.",
        tool_calls=[MockLLMToolCall("list_directory", {"path": "."})]
    )
    
    # Response 2: After list_directory, create a file
    server.add_response(
        r"CREATE_FILE",
        "I've created the file as requested.",
        tool_calls=[MockLLMToolCall("create_file", {"path": "test.txt", "content": "Hello, World!"})]
    )
    
    # Response 3: After create_file, respond to user
    server.add_response(
        r"respond_to_user",
        "Task completed successfully!",
        tool_calls=[MockLLMToolCall("respond_to_user", {"message": "Task completed successfully!"})]
    )
    
    return server


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Mock OpenAI-compatible LLM endpoint')
    parser.add_argument('--port', type=int, default=18765, help='Port to listen on')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='Host to bind to')
    args = parser.parse_args()
    
    server = MockLLMServer(host=args.host, port=args.port)
    port = server.start()
    
    # Create default responses
    create_default_responses()
    
    try:
        # Keep the server running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
