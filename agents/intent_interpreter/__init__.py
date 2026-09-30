"""
Intent Interpreter Agent.

Converts free-form user prompts into structured instructions that drive
the entire HLD generation pipeline. This is the critical innovation that
transforms the system from passive RAG into intent-driven architecture.

Usage:
    interpreter = IntentInterpreter()
    structured_intent = await interpreter.interpret(
        user_prompt="Include only BSF and SCP. Use IPs from network plan.",
        product="5G_SBA",
        available_components=["SCP", "BSF", "SEPP", ...],
        document_filenames=["5G_Architecture.pdf", "Network_Plan.xlsx"]
    )
"""

from .interpreter import IntentInterpreter
from .schemas import StructuredIntent

__all__ = ["IntentInterpreter", "StructuredIntent"]
