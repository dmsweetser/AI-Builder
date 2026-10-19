"""Utility functions."""

def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b

def divide(a: float, b: float) -> float:
    """Divide a by b."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b

def format_result(label: str, value) -> str:
    """Format a result for display."""
    return f"{label}: {value}"
