"""
LangGraph builder for Document Analyzer Agent.

New streamlined pipeline (Cognee-free):
parse → extract_images → semantic_extract → merge_and_validate
"""

from langgraph.graph import StateGraph, END
import sys
from pathlib import Path

# Add to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from hld_generator.agents.document_analyzer.state.schema import AnalyzerState
from hld_generator.agents.document_analyzer.graph import nodes


def build_agent_graph() -> StateGraph:
    """
    Build the Document Analyzer Agent's LangGraph.

    New streamlined pipeline (4 nodes):
        1. parse - Parse document with Docling (extract text, tables, images)
        2. extract_images - OCI Vision analysis of images
        3. semantic_extract - Semantic chunking + parallel LLM extraction
        4. merge_and_validate - Merge chunks + inject tables/images + validate

    No Cognee dependency - direct LLM extraction for speed and accuracy.

    Returns:
        Compiled StateGraph ready for execution
    """
    # Create graph with AnalyzerState
    graph = StateGraph(AnalyzerState)

    # Add nodes (4 nodes total)
    graph.add_node("parse", nodes.parse_document_node)
    graph.add_node("extract_images", nodes.extract_images_node)
    graph.add_node("semantic_extract", nodes.semantic_extract_node)
    graph.add_node("merge_and_validate", nodes.merge_and_validate_node)

    # Define linear flow
    graph.set_entry_point("parse")
    graph.add_edge("parse", "extract_images")
    graph.add_edge("extract_images", "semantic_extract")
    graph.add_edge("semantic_extract", "merge_and_validate")
    graph.add_edge("merge_and_validate", END)

    return graph.compile()


def build_agent_graph_with_refinement() -> StateGraph:
    """
    Enhanced graph with refinement loop.
    
    After synthesis, if completeness_score < threshold,
    can loop back to extract for additional queries.
    
    (Not implemented yet - placeholder for future enhancement)
    """
    raise NotImplementedError("Refinement loop not yet implemented")
