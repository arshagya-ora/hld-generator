"""
LangGraph builder for Assembly Agent pipeline.

Constructs a 9-node sequential pipeline:
1. initialize - Validate inputs
2. compile_sections - Merge all sections
3. auto_number - Assign numbers
4. generate_toc - Create TOC and lists
5. generate_executive_summary - LLM-generated exec summary
6. generate_appendices - Create appendices
7. run_quality_checks - Validate assembled document
8. export_documents - Export to formats
9. finalize - Create final output
"""

from langgraph.graph import StateGraph, END

from hld_generator.agents.assembly.state.schema import AssemblyState
from hld_generator.agents.assembly.graph import nodes


def build_assembly_graph(llm_client) -> StateGraph:
    """
    Build LangGraph for assembly pipeline.

    Args:
        llm_client: LLM client for executive summary generation

    Returns:
        Compiled StateGraph ready for execution
    """

    graph = StateGraph(AssemblyState)

    # ============================
    # Define Nodes
    # ============================

    graph.add_node("initialize", nodes.initialize_node)
    graph.add_node("compile_sections", nodes.compile_sections_node)
    graph.add_node("auto_number", nodes.auto_number_node)

    # Parallel generation node: TOC + Executive Summary run concurrently (saves ~7s)
    async def _parallel_generation_node(state):
        import asyncio

        # Run TOC and executive summary in parallel
        toc_task = nodes.generate_toc_node(state)
        exec_summary_task = nodes.generate_executive_summary_node(state, llm_client)

        toc_result, exec_summary_result = await asyncio.gather(toc_task, exec_summary_task)

        # Merge results
        merged_result = {**toc_result, **exec_summary_result}
        return merged_result

    graph.add_node("parallel_generation", _parallel_generation_node)

    async def _appendices_node(state):
        return await nodes.generate_appendices_node(state, llm_client)

    graph.add_node("generate_appendices", _appendices_node)
    graph.add_node("run_quality_checks", nodes.quality_checks_node)
    graph.add_node("export_documents", nodes.export_documents_node)
    graph.add_node("finalize", nodes.finalize_node)

    # ============================
    # Define Edges (Optimized Pipeline with Parallel TOC + Exec Summary)
    # ============================

    graph.set_entry_point("initialize")
    graph.add_edge("initialize", "compile_sections")
    graph.add_edge("compile_sections", "auto_number")
    graph.add_edge("auto_number", "parallel_generation")  # Fork: TOC + exec summary in parallel
    graph.add_edge("parallel_generation", "generate_appendices")  # Join
    graph.add_edge("generate_appendices", "run_quality_checks")
    graph.add_edge("run_quality_checks", "export_documents")
    graph.add_edge("export_documents", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()
