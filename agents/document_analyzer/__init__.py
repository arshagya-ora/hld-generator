"""
Document Analyzer Agent

Analyzes documents (PID, RFP, specs) and extracts structured project knowledge
using a three-phase pipeline: Discovery -> Extraction -> Synthesis.

Exposes:
    - DocumentAnalyzerAgent: Main agent class
    - DocumentKnowledgeBase: Output Pydantic model
"""

from .agent import DocumentAnalyzerAgent
from .state.models import DocumentKnowledgeBase

__all__ = ["DocumentAnalyzerAgent", "DocumentKnowledgeBase"]
