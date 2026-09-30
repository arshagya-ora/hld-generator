"""
Integration & E2E tests for Phases 1-5 of the agentic HLD Generator.

Tests are UNIT-level (no LLM calls, no OCI, no Cognee).
They verify the deterministic logic in each phase.

Run: python -m pytest tests/test_agentic_phases.py -v
"""

import pytest
import sys
import importlib
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def _import_module(dotted_path):
    """Import a module directly, bypassing package __init__.py if possible."""
    # For schemas modules that have __init__.py pulling in heavy deps,
    # load the .py file directly using importlib.util
    root = Path(__file__).parent.parent
    parts = dotted_path.split(".")
    file_path = root / Path(*parts[:-1]) / f"{parts[-1]}.py"
    if file_path.exists():
        spec = importlib.util.spec_from_file_location(dotted_path, file_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[dotted_path] = mod
        spec.loader.exec_module(mod)
        return mod
    return importlib.import_module(dotted_path)


# Reusable skipif for modules needing OCI adapter (requires `instructor`)
_oci_available = True
try:
    import instructor  # noqa: F401
except ImportError:
    _oci_available = False

requires_oci = pytest.mark.skipif(not _oci_available, reason="OCI adapter dependencies not installed (instructor)")


# ─────────────────────────────────────────────────────────────────────
# Phase 1: Intent Interpreter Schema Tests
# ─────────────────────────────────────────────────────────────────────

class TestIntentInterpreterSchemas:
    """Test StructuredIntent schema validation (no OCI dependency)."""

    def _schemas(self):
        """Import schemas module directly (bypasses __init__.py which pulls in OCI)."""
        return _import_module("agents.intent_interpreter.schemas")

    def test_structured_intent_defaults(self):
        schemas = self._schemas()
        intent = schemas.StructuredIntent()
        assert intent.intent_type == "FULL_GENERATION"
        assert intent.component_scope.mode.value == "INCLUSIVE"
        assert intent.component_scope.preserve_structural is True
        assert intent.custom_sections == []
        assert intent.style_directives == {}

    def test_structured_intent_exclusive_mode(self):
        schemas = self._schemas()

        intent = schemas.StructuredIntent(
            intent_type="SELECTIVE_GENERATION",
            component_scope=schemas.ComponentScope(
                mode=schemas.ComponentScopeMode.EXCLUSIVE,
                include=["BSF", "SCP"],
            ),
        )
        assert intent.component_scope.mode == schemas.ComponentScopeMode.EXCLUSIVE
        assert "BSF" in intent.component_scope.include
        assert "SCP" in intent.component_scope.include

    def test_structured_intent_with_style_directives(self):
        schemas = self._schemas()

        intent = schemas.StructuredIntent(
            style_directives={
                "sec_deployment": schemas.StyleDirective(
                    detail_level="high-level",
                    max_subsections=3,
                    estimated_tokens=500,
                ),
            },
        )
        d = intent.style_directives["sec_deployment"]
        assert d.detail_level == "high-level"
        assert d.max_subsections == 3
        assert d.estimated_tokens == 500

    def test_structured_intent_with_custom_sections(self):
        schemas = self._schemas()

        intent = schemas.StructuredIntent(
            custom_sections=[
                schemas.CustomSection(
                    section_id="sec_migration_strategy",
                    title="Migration Strategy",
                    insert_after="sec_deployment",
                    generation_strategy="hybrid",
                ),
            ],
        )
        assert len(intent.custom_sections) == 1
        assert intent.custom_sections[0].title == "Migration Strategy"

    def test_structured_intent_serialization(self):
        schemas = self._schemas()

        intent = schemas.StructuredIntent(raw_user_prompt="test prompt")
        d = intent.model_dump()
        assert isinstance(d, dict)
        assert d["raw_user_prompt"] == "test prompt"
        assert "component_scope" in d


# ─────────────────────────────────────────────────────────────────────
# Phase 4: Blueprint Intent Filter Tests
# ─────────────────────────────────────────────────────────────────────

class TestIntentSectionFilter:
    """Test deterministic section filtering by structured intent."""

    @pytest.fixture
    def sample_kb_sections(self):
        return [
            {"section_id": "sec_introduction", "title": "Introduction", "section_number": "1", "category": "structural"},
            {"section_id": "sec_bsf_architecture", "title": "BSF Architecture", "section_number": "5", "component": "BSF"},
            {"section_id": "sec_scp_architecture", "title": "SCP Architecture", "section_number": "6", "component": "SCP"},
            {"section_id": "sec_amf_architecture", "title": "AMF Architecture", "section_number": "7", "component": "AMF"},
            {"section_id": "sec_deployment", "title": "Deployment", "section_number": "8", "category": "structural"},
            {"section_id": "sec_appendix_a", "title": "Appendix A: Acronyms", "section_number": "A"},
        ]

    def _filter(self):
        return _import_module("agents.blueprint.tools.intent_section_filter")

    def test_no_intent_returns_all(self, sample_kb_sections):
        m = self._filter()
        result = m.filter_sections_by_intent(sample_kb_sections, None)
        assert len(result) == len(sample_kb_sections)

    def test_empty_intent_returns_all(self, sample_kb_sections):
        m = self._filter()
        result = m.filter_sections_by_intent(sample_kb_sections, {})
        assert len(result) == len(sample_kb_sections)

    def test_exclusive_mode_filters_components(self, sample_kb_sections):
        m = self._filter()

        intent = {
            "component_scope": {
                "mode": "EXCLUSIVE",
                "include": ["BSF", "SCP"],
                "exclude": [],
                "preserve_structural": True,
            },
        }
        result = m.filter_sections_by_intent(sample_kb_sections, intent)

        result_ids = [s["section_id"] for s in result]

        # BSF and SCP should be included
        assert "sec_bsf_architecture" in result_ids
        assert "sec_scp_architecture" in result_ids
        # AMF should be excluded
        assert "sec_amf_architecture" not in result_ids
        # Structural sections should be preserved
        assert "sec_introduction" in result_ids
        assert "sec_deployment" in result_ids
        assert "sec_appendix_a" in result_ids

    def test_inclusive_mode_excludes_components(self, sample_kb_sections):
        m = self._filter()

        intent = {
            "component_scope": {
                "mode": "INCLUSIVE",
                "include": [],
                "exclude": ["AMF"],
                "preserve_structural": True,
            },
        }
        result = m.filter_sections_by_intent(sample_kb_sections, intent)

        result_ids = [s["section_id"] for s in result]

        assert "sec_amf_architecture" not in result_ids
        assert "sec_bsf_architecture" in result_ids
        assert "sec_scp_architecture" in result_ids

    def test_emphasis_mode_marks_sections(self, sample_kb_sections):
        m = self._filter()

        intent = {
            "component_scope": {
                "mode": "EMPHASIS",
                "include": ["BSF"],
                "exclude": [],
                "preserve_structural": True,
            },
        }
        result = m.filter_sections_by_intent(sample_kb_sections, intent)

        # All sections should be present
        assert len(result) == len(sample_kb_sections)

        # BSF should be emphasized
        bsf = next(s for s in result if s["section_id"] == "sec_bsf_architecture")
        assert bsf.get("_emphasized") is True

        # SCP should NOT be emphasized
        scp = next(s for s in result if s["section_id"] == "sec_scp_architecture")
        assert not scp.get("_emphasized")

    def test_custom_section_insertion(self, sample_kb_sections):
        m = self._filter()

        intent = {
            "custom_sections": [
                {
                    "section_id": "sec_migration",
                    "title": "Migration Strategy",
                    "insert_after": "sec_deployment",
                    "generation_strategy": "hybrid",
                },
            ],
        }
        result = m.insert_custom_sections(sample_kb_sections, intent)

        result_ids = [s["section_id"] for s in result]

        assert "sec_migration" in result_ids

        deploy_idx = result_ids.index("sec_deployment")
        migration_idx = result_ids.index("sec_migration")
        assert migration_idx == deploy_idx + 1

    def test_style_directives_annotation(self, sample_kb_sections):
        m = self._filter()

        intent = {
            "component_scope": {"mode": "INCLUSIVE", "include": [], "exclude": [], "preserve_structural": True},
            "style_directives": {
                "sec_deployment": {
                    "detail_level": "high-level",
                    "estimated_tokens": 500,
                },
            },
        }
        result = m.filter_sections_by_intent(sample_kb_sections, intent)

        deploy = next(s for s in result if s["section_id"] == "sec_deployment")
        assert deploy["_style_override"]["detail_level"] == "high-level"
        assert deploy["_style_override"]["estimated_tokens"] == 500

    def test_intent_context_for_prompt(self):
        m = self._filter()

        intent = {
            "intent_type": "SELECTIVE_GENERATION",
            "component_scope": {"mode": "EXCLUSIVE", "include": ["BSF", "SCP"]},
            "raw_user_prompt": "Generate HLD for BSF and SCP only",
        }
        result = m.build_intent_context_for_prompt(intent)

        assert "SELECTIVE_GENERATION" in result
        assert "BSF" in result
        assert "SCP" in result


# ─────────────────────────────────────────────────────────────────────
# Phase 5: Assembly Quality Checks Tests
# ─────────────────────────────────────────────────────────────────────

class TestQualityChecker:
    """Test assembly quality checks."""

    @pytest.fixture
    def checker(self):
        m = _import_module("agents.assembly.tools.quality_checks")
        return m.QualityChecker()

    def test_section_numbering_pass(self, checker):
        sections = {
            "s1": {"section_number": "1", "section_id": "sec_intro"},
            "s2": {"section_number": "2", "section_id": "sec_scope"},
            "s3": {"section_number": "3", "section_id": "sec_arch"},
        }
        result = checker.check_section_numbering(sections)
        assert result["status"] == "pass"

    def test_section_numbering_gap(self, checker):
        sections = {
            "s1": {"section_number": "1", "section_id": "sec_intro"},
            "s2": {"section_number": "2", "section_id": "sec_scope"},
            "s3": {"section_number": "4", "section_id": "sec_deploy"},
        }
        result = checker.check_section_numbering(sections)
        assert result["status"] == "warning"
        assert "2 → 4" in result["details"]

    def test_orphaned_placeholders_pass(self, checker):
        content = "# Section 1\n\nNo placeholders here.\n\n![Figure 1.1](img_001.png)"
        result = checker.check_orphaned_placeholders(content)
        assert result["status"] == "pass"

    def test_orphaned_placeholders_fail(self, checker):
        content = "# Section 1\n\n{{FIGURE:img_006_538e35e4}}\n\nSome text {{TABLE:tbl_001}}"
        result = checker.check_orphaned_placeholders(content)
        assert result["status"] == "fail"
        assert "img_006_538e35e4" in result["details"]

    def test_meta_commentary_pass(self, checker):
        sections = {
            "s1": {
                "section_id": "sec_intro",
                "title": "Introduction",
                "markdown_content": "The DSR system deploys across two sites: UPW and PJB.",
            },
        }
        result = checker.check_meta_commentary(sections)
        assert result["status"] == "pass"

    def test_meta_commentary_warning(self, checker):
        sections = {
            "s1": {
                "section_id": "sec_arch",
                "title": "Architecture",
                "markdown_content": "The reference materials indicate that the system uses DA-MP components.",
            },
        }
        result = checker.check_meta_commentary(sections)
        assert result["status"] == "warning"

    def test_acronyms_valid_pass(self, checker):
        content = "| DSR | Diameter Signaling Router |\n| IPFE | IP Front End |"
        result = checker.check_acronyms_valid(content)
        assert result["status"] == "pass"

    def test_toc_completeness_pass(self, checker):
        toc = "1. Introduction\n2. Scope\n3. Architecture"
        sections = {
            "s1": {"section_number": "1", "section_id": "sec_intro"},
            "s2": {"section_number": "2", "section_id": "sec_scope"},
            "s3": {"section_number": "3", "section_id": "sec_arch"},
        }
        result = checker.check_toc_completeness(toc, sections)
        assert result["status"] == "pass"

    def test_toc_completeness_warning(self, checker):
        toc = "1. Introduction"
        sections = {
            "s1": {"section_number": "1", "section_id": "sec_intro"},
            "s2": {"section_number": "2", "section_id": "sec_scope"},
            "s3": {"section_number": "3", "section_id": "sec_arch"},
            "s4": {"section_number": "4", "section_id": "sec_deploy"},
        }
        result = checker.check_toc_completeness(toc, sections)
        assert result["status"] == "warning"

    def test_appendix_order_pass(self, checker):
        content = "## Appendix A: Acronyms\n\nContent...\n\n## Appendix B: References\n\nContent..."
        result = checker.check_appendix_order(content)
        assert result["status"] == "pass"
        assert result["details"] == "Appendix order correct: ['A', 'B']"

    def test_appendix_order_wrong(self, checker):
        content = "## Appendix B: References\n\nContent...\n\n## Appendix A: Acronyms\n\nContent..."
        result = checker.check_appendix_order(content)
        assert result["status"] == "warning"

    def test_check_all_integration(self, checker):
        result = checker.check_all(
            compiled_markdown="# Section 1\n\nNo issues here.",
            sections={
                "s1": {"section_number": "1", "section_id": "sec_intro", "markdown_content": "Hello world"},
            },
            toc_content="1. Introduction",
            appendices_content="## Appendix A: Acronyms\n| DSR | Router |",
            executive_summary="This document...",
        )
        assert "passed" in result
        assert "checks" in result
        assert len(result["checks"]) == 6
        assert result["passed"] is True


# ─────────────────────────────────────────────────────────────────────
# Phase 2: Enhanced Document Intelligence Tests
# ─────────────────────────────────────────────────────────────────────

class TestCogneeIntentSearch:
    """Test intent-based search logic (simulated, no OCI/Cognee connection)."""

    @requires_oci
    def test_search_with_intent_import(self):
        """Verify search_with_intent method exists on CogneeWrapper."""
        from shared.cognee_wrapper import CogneeWrapper
        assert hasattr(CogneeWrapper, "search_with_intent")

    def test_intent_filter_component_scope(self):
        """Test that component_scope post-filtering logic works."""
        results = [
            {"text": "BSF handles authentication", "score": 0.9},
            {"text": "AMF manages access", "score": 0.8},
            {"text": "SCP provides service comm", "score": 0.7},
        ]

        intent = {
            "component_scope": {
                "mode": "EXCLUSIVE",
                "include": ["BSF", "SCP"],
            },
        }

        include = [c.lower() for c in intent["component_scope"]["include"]]

        filtered = [
            r for r in results
            if any(comp in r["text"].lower() for comp in include)
        ]

        assert len(filtered) == 2
        assert "BSF" in filtered[0]["text"]
        assert "SCP" in filtered[1]["text"]


# ─────────────────────────────────────────────────────────────────────
# Phase 3: Agentic Document Analyzer Tests
# ─────────────────────────────────────────────────────────────────────

class TestAgenticDocumentAnalyzer:
    """Test agentic document analyzer components (requires OCI deps)."""

    @requires_oci
    def test_retrieval_tools_import(self):
        from agents.document_analyzer.tools.retrieval_tools import RetrievalTools
        assert RetrievalTools is not None

    @requires_oci
    def test_agentic_executor_import(self):
        from agents.document_analyzer.agentic_executor import AgenticDocumentAnalyzer
        assert AgenticDocumentAnalyzer is not None

    @requires_oci
    def test_agentic_node_in_graph(self):
        from agents.document_analyzer.graph.nodes import agentic_retrieval_node
        assert callable(agentic_retrieval_node)


# ─────────────────────────────────────────────────────────────────────
# Cross-Phase Integration Tests
# ─────────────────────────────────────────────────────────────────────

class TestCrossPhaseIntegration:
    """Test that structured_intent flows through the full pipeline."""

    @requires_oci
    def test_blueprint_state_has_structured_intent(self):
        from agents.blueprint.state.models import BlueprintState
        annotations = BlueprintState.__annotations__
        assert "structured_intent" in annotations

    @requires_oci
    def test_analyzer_state_has_structured_intent(self):
        from agents.document_analyzer.state.schema import AnalyzerState
        annotations = AnalyzerState.__annotations__
        assert "structured_intent" in annotations

    def test_section_plan_has_hallucination_guards(self):
        """Verify hallucination_guards survives Pydantic SectionPlan validation."""
        models = _import_module("agents.blueprint.state.models")
        section_dict = {
            "section_id": "sec_test",
            "section_number": "1",
            "title": "Test Section",
            "hallucination_guards": ["IP addresses", "hostnames", "software versions"],
        }
        plan = models.SectionPlan(**section_dict)
        dumped = plan.model_dump()
        assert "hallucination_guards" in dumped
        assert len(dumped["hallucination_guards"]) == 3
        assert "IP addresses" in dumped["hallucination_guards"]

    def test_assembly_state_has_quality_checks(self):
        m = _import_module("agents.assembly.state.schema")
        annotations = m.AssemblyState.__annotations__
        assert "quality_checks" in annotations

    def test_intent_to_section_filter_round_trip(self):
        """Test full round trip: StructuredIntent → filter → annotated sections."""
        schemas = _import_module("agents.intent_interpreter.schemas")
        filter_mod = _import_module("agents.blueprint.tools.intent_section_filter")

        # Create intent
        intent = schemas.StructuredIntent(
            intent_type="SELECTIVE_GENERATION",
            component_scope=schemas.ComponentScope(
                mode=schemas.ComponentScopeMode.EXCLUSIVE,
                include=["DSR"],
            ),
            style_directives={
                "sec_deployment": schemas.StyleDirective(detail_level="high-level"),
            },
        )

        # Create KB sections
        kb_sections = [
            {"section_id": "sec_introduction", "title": "Intro", "section_number": "1", "category": "structural"},
            {"section_id": "sec_dsr_architecture", "title": "DSR Architecture", "section_number": "5", "component": "DSR"},
            {"section_id": "sec_ipfe_architecture", "title": "IPFE Architecture", "section_number": "6", "component": "IPFE"},
            {"section_id": "sec_deployment", "title": "Deployment", "section_number": "8", "category": "structural"},
        ]

        # Serialize intent to dict (as it would be in state)
        intent_dict = intent.model_dump()

        # Filter
        filtered = filter_mod.filter_sections_by_intent(kb_sections, intent_dict)
        result_ids = [s["section_id"] for s in filtered]

        # DSR included, IPFE excluded, structural preserved
        assert "sec_dsr_architecture" in result_ids
        assert "sec_ipfe_architecture" not in result_ids
        assert "sec_introduction" in result_ids
        assert "sec_deployment" in result_ids

        # Style directive applied
        deploy = next(s for s in filtered if s["section_id"] == "sec_deployment")
        assert deploy["_style_override"]["detail_level"] == "high-level"
