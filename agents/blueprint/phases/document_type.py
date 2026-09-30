"""
Phase 1: Document Type & Product Identification

Reads DocumentKnowledgeBase (products, document_intelligence) and uses the
ProductProfileLoader to identify which product profile to load. Extracts global template
variables (customer_name, project_name, NF list, site names, deployment model).

Classifies deployment type using LLM: Greenfield, Upgrade, Project Expansion, or Project Initiation.
"""

import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

from hld_generator.agents.blueprint.tools.product_profile_loader import ProductProfileLoader, ProductProfile
from hld_generator.agents.blueprint.phases.global_planning import (
    build_section_dependency_graph,
    evaluate_global_conditionals,
    build_global_context,
)
from hld_generator.shared.llm_wrapper import OCILLMWrapper
from hld_generator.shared.logging_config import setup_logger

logger = setup_logger(__name__)


class DocumentTypePhase:
    """
    Phase 1: Identify product and extract global template variables.

    This phase:
    1. Reads the DocumentKnowledgeBase from the Document Analyzer
    2. Matches extracted products to available profiles via ProductProfileLoader
    3. Loads the product profile for downstream phases
    4. Extracts global template variables for all sections
    5. Classifies deployment type (Greenfield, Upgrade, Expansion, Initiation)
    """

    def __init__(self, profile_loader: ProductProfileLoader, llm: OCILLMWrapper):
        self.profile_loader = profile_loader
        self.llm = llm

    async def execute(
        self,
        knowledge_base: Dict[str, Any],
        image_inventory: Optional[Dict[str, Any]] = None,
        user_prompt: str = "",
        structured_intent: Optional[Dict[str, Any]] = None,
        product_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute Phase 1.

        Args:
            knowledge_base: DocumentKnowledgeBase as dict
            image_inventory: ImageInventory as dict (optional)
            user_prompt: User's input text (optional, for extracting customer name overrides)
            structured_intent: StructuredIntent dict (optional)
            product_id: Product ID from job (e.g., "Sessions", "DSR", "5G_SBA")
                       If provided, uses this instead of auto-detecting from keywords.
                       CRITICAL for product ID consistency.

        Returns:
            Dict with:
              - identified_product: str
              - product_profile: dict (loaded ProductProfile)
              - template_variables: dict
              - document_type: str
        """
        logger.info("Phase 1: Document Type & Product Identification")

        # CRITICAL: Use provided product_id if available (from job.product_id)
        # This ensures product ID consistency across frontend → backend → all agents
        if product_id:
            logger.info(f"  Using provided product_id from job: {product_id}")
            identified_product = product_id

            # Validate that the product profile exists
            available_products = self.profile_loader.list_products()
            if identified_product not in available_products:
                raise ValueError(
                    f"Product ID '{identified_product}' from job does not have a corresponding profile. "
                    f"Available products: {available_products}. "
                    f"Create product_profiles/{identified_product}.json or set PRODUCT_PROFILE_DIR."
                )
        else:
            # Fallback: Auto-detect product from keywords (legacy behavior)
            logger.warning("  No product_id provided - auto-detecting from keywords (not recommended)")

            # Step 1: Extract product keywords from user_prompt (PRIORITY) and DocumentKnowledgeBase
            product_keywords = self._extract_product_keywords(knowledge_base, user_prompt)
            logger.info(f"  Extracted product keywords: {product_keywords}")

            # Step 2: Match to available profiles
            identified_product = self.profile_loader.find_product_for_keywords(product_keywords)

        if not identified_product:
            # Fallback: try the first available product
            available = self.profile_loader.list_products()
            if available:
                identified_product = available[0]
                logger.warning(
                    f"  Could not match products. Falling back to: {identified_product}"
                )
            else:
                raise ValueError(
                    "No product profiles available. Create a product profile JSON. "
                    f"Keywords tried: {product_keywords}"
                )

        logger.info(f"  Identified product: {identified_product}")

        # Step 3: Load the product profile
        product_profile = self.profile_loader.load_product_profile(identified_product)
        logger.info(f"  Loaded product profile: {product_profile.summary()}")

        # Step 4: Extract global template variables (Stage A: deterministic fields)
        template_variables = self._extract_template_variables(
            knowledge_base, identified_product, product_profile, user_prompt, structured_intent
        )
        logger.info(f"  Template variables (Stage A): {list(template_variables.keys())}")

        # Stage B: LLM enrichment — fills in any placeholder values from the document-derived knowledge
        template_variables = await self._extract_template_variables_via_llm(
            knowledge_base, template_variables
        )
        logger.info(f"  Template variables (Stage B): {template_variables}")

        # Step 5: Classify deployment type using LLM
        document_type = await self._classify_deployment_type(knowledge_base)
        logger.info(f"  Classified deployment type: {document_type}")

        # Step 6: Build global planning context for section-by-section planning
        logger.info("  Building global planning context...")
        product_profile_dict = product_profile.to_dict()

        dependency_graph = build_section_dependency_graph(product_profile_dict.get("sections", []))
        conditional_hints = evaluate_global_conditionals(
            product_profile_dict,
            template_variables,
            knowledge_base
        )
        global_context = build_global_context(product_profile_dict)

        global_planning_context = {
            "planning_instructions": global_context.get("planning_instructions", {}),
            "section_ordering_rules": global_context.get("section_ordering_rules", {}),
            "nf_architecture_pattern": global_context.get("nf_architecture_pattern", {}),
            "product_specific_sections": global_context.get("product_specific_sections", {}),
            "validation_rules": global_context.get("validation_rules", {}),
            "dependency_graph": dependency_graph,
            "conditional_hints": conditional_hints,
        }

        logger.info(f"  Global planning context built: {len(dependency_graph)} sections in dependency graph")

        return {
            "identified_product": identified_product,
            "product_profile": product_profile_dict,
            "template_variables": template_variables,
            "document_type": document_type,
            "global_planning_context": global_planning_context,
        }

    def _extract_product_keywords(
        self,
        knowledge_base: Dict[str, Any],
        user_prompt: str = "",
    ) -> List[str]:
        """
        Extract product-identifying keywords from DocumentKnowledgeBase and user prompt.

        PRIORITY: user_prompt > document_intelligence

        Pulls from:
          - user_prompt (PRIORITY - explicit product mentions)
          - document_intelligence.primary_products
          - products dict keys
          - product names from ProductInfo objects
        """
        import re

        keywords = []

        # PRIORITY 1: Extract from user_prompt (explicit product mentions)
        if user_prompt:
            # Pattern 1: "Product: Sessions" or "Product name: 5G_SBA"
            match = re.search(r'[Pp]roduct(?:\s+name)?:\s*([A-Za-z0-9_\s-]+?)(?:\s|$|,|\.)', user_prompt)
            if match:
                product_name = match.group(1).strip()
                keywords.append(product_name)

            # Pattern 2: "for Sessions deployment", "Sessions HLD", "Sessions product"
            match = re.search(r'(?:for\s+|HLD\s+for\s+)([A-Za-z0-9_]+)\s+(?:deployment|HLD|product|design)', user_prompt)
            if match:
                product_name = match.group(1).strip()
                keywords.append(product_name)

            # Pattern 3: Known product names in user prompt (Sessions, DSR, 5G_SBA, 5G SBA)
            known_products = ['Sessions', 'DSR', '5G_SBA', '5G SBA', 'SBA']
            for prod in known_products:
                if re.search(r'\b' + re.escape(prod) + r'\b', user_prompt, re.IGNORECASE):
                    keywords.append(prod)

        # From document_intelligence
        doc_intel = knowledge_base.get("document_intelligence", {})
        primary_products = doc_intel.get("primary_products", [])
        keywords.extend(primary_products)

        # From products dict
        products = knowledge_base.get("products", {})
        keywords.extend(products.keys())

        # From product info names
        for prod_info in products.values():
            if isinstance(prod_info, dict):
                name = prod_info.get("name", "")
                if name:
                    keywords.append(name)
                # Also check components for NF names
                components = prod_info.get("components", [])
                keywords.extend(components)
            elif hasattr(prod_info, "name"):
                keywords.append(prod_info.name)

        # From project name (may contain product hints)
        project_name = doc_intel.get("project_name", "")
        if project_name:
            keywords.extend(project_name.split())

        # Deduplicate while preserving order
        seen = set()
        unique_keywords = []
        for kw in keywords:
            kw_lower = kw.lower().strip()
            if kw_lower and kw_lower not in seen:
                seen.add(kw_lower)
                unique_keywords.append(kw.strip())

        return unique_keywords

    def _extract_customer_from_user_prompt(self, user_prompt: str) -> str:
        """
        Extract customer name from user prompt text using simple pattern matching.

        Looks for patterns like:
        - "Customer: SaudiTel"
        - "customer name: Vodafone"
        - "for SaudiTel customer"
        - "SaudiTel deployment"

        Returns:
            Extracted customer name or empty string
        """
        import re

        # Pattern 1: "Customer: <name>" or "Customer name: <name>"
        match = re.search(r'[Cc]ustomer(?:\s+name)?:\s*([A-Z][A-Za-z0-9\s]+?)(?:\s|$|,|\.)', user_prompt)
        if match:
            return match.group(1).strip()

        # Pattern 2: "for <name> customer" or "<name> deployment"
        match = re.search(r'for\s+([A-Z][A-Za-z0-9\s]+?)\s+(?:customer|deployment|project)', user_prompt)
        if match:
            return match.group(1).strip()

        # Pattern 3: First capitalized word if it looks like a company name
        match = re.search(r'\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\b', user_prompt)
        if match:
            candidate = match.group(1).strip()
            # Filter out common non-customer words
            excluded = ['Communications', 'HLD', 'Design', 'Document', 'Sessions', 'Product']
            if candidate not in excluded:
                return candidate

        return ""

    def _extract_template_variables(
        self,
        knowledge_base: Dict[str, Any],
        product: str,
        product_profile: ProductProfile,
        user_prompt: str = "",
        structured_intent: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """
        Extract global template variables that will be injected into all sections.

        These come from the DocumentKnowledgeBase and the product profile's
        global.template_variables.global definitions.

        Args:
            knowledge_base: Document Analyzer output
            product: Identified product
            product_profile: Product profile
            user_prompt: User's input text (overrides customer name if provided)
            structured_intent: StructuredIntent dict (from Intent Interpreter) with template_variable_overrides
        """
        doc_intel = knowledge_base.get("document_intelligence", {})
        products = knowledge_base.get("products", {})
        sites = knowledge_base.get("sites", [])
        capacity = knowledge_base.get("capacity_and_sizing", {}) or {}
        infra = knowledge_base.get("infrastructure", {}) or {}

        # Customer name - PRIORITY: structured_intent > user_prompt regex > document_intelligence > profile default
        customer_name = ""

        # 1. Check structured_intent overrides (from Intent Interpreter - highest priority)
        if structured_intent:
            customer_name = structured_intent.get("template_variable_overrides", {}).get("customer_name", "")
            if customer_name:
                logger.info(f"  Using customer_name from structured_intent: {customer_name}")

        # 2. Try to extract from user_prompt (regex patterns - fallback)
        if not customer_name and user_prompt:
            customer_name = self._extract_customer_from_user_prompt(user_prompt)
            if customer_name:
                logger.info(f"  Extracted customer_name from user_prompt regex: {customer_name}")

        # 3. Fall back to document_intelligence
        if not customer_name:
            customer_name = doc_intel.get("customer", "")
            if customer_name:
                logger.info(f"  Using customer_name from document_intelligence: {customer_name}")

        # 4. Fall back to profile default
        if not customer_name:
            profile_globals = product_profile.global_config.get("template_variables", {}).get("global", {})
            customer_name = profile_globals.get("customer_name", {}).get("default", "[Customer Name]")
            logger.info(f"  Using customer_name from profile default: {customer_name}")

        # Project name - PRIORITY: structured_intent > document_intelligence > default
        project_name = ""

        # 1. Check structured_intent overrides
        if structured_intent:
            project_name = structured_intent.get("template_variable_overrides", {}).get("project_name", "")

        # 2. Fall back to document_intelligence
        if not project_name:
            project_name = doc_intel.get("project_name", "")

        # 3. Fall back to default
        if not project_name:
            project_name = f"{product} Deployment"

        # NF / product component list (reads from profile metadata)
        nf_list = self._extract_nf_list(products, product_profile)

        # Site names - PRIORITY: structured_intent > document_intelligence > default
        site_names = []

        # 1. Check structured_intent overrides
        if structured_intent:
            site_names_override = structured_intent.get("template_variable_overrides", {}).get("site_names", "")
            if site_names_override:
                site_names = [s.strip() for s in site_names_override.split(",") if s.strip()]
                logger.info(f"  Using site_names from structured_intent: {site_names}")

        # 2. Fall back to document_intelligence
        if not site_names:
            for site in sites:
                if isinstance(site, dict):
                    site_names.append(site.get("name", ""))
                elif hasattr(site, "name"):
                    site_names.append(site.name)
            site_names = [s for s in site_names if s]

        # Deployment model - PRIORITY: structured_intent > document_intelligence > inferred
        deployment_model = ""

        # 1. Check structured_intent overrides
        if structured_intent:
            deployment_model = structured_intent.get("template_variable_overrides", {}).get("deployment_model", "")
            if deployment_model:
                logger.info(f"  Using deployment_model from structured_intent: {deployment_model}")

        # 2. Fall back to document_intelligence
        if not deployment_model:
            deployment_model = infra.get("deployment_model", "")

        # 3. Infer from site count
        if not deployment_model:
            if len(site_names) > 1:
                deployment_model = "Multi-site deployment"
            elif len(site_names) == 1:
                deployment_model = "Single-site deployment"

        # Multi-site flag
        multi_site = len(site_names) > 1

        # Stage A variables — deterministic fields with known paths in the DA output.
        # platform_version, product_version, and other infra-derived fields are
        # extracted by the LLM in Stage B (_extract_template_variables_via_llm)
        # because their field names vary across DA runs.
        variables = {
            "customer_name": customer_name,
            "project_name": project_name,
            "product": product,
            "nf_list": ", ".join(nf_list) if nf_list else product,
            "site_names": ", ".join(site_names) if site_names else "[Site Names]",
            "site_count": str(len(site_names)),
            "deployment_model": deployment_model or "[Deployment Model]",
            "multi_site_deployment": str(multi_site).lower(),
            # Placeholders filled in by LLM Stage B (or structured_intent overrides)
            "platform_version": "[platform_version]",
            "product_version": "[product_version]",
        }

        # Apply additional template variable overrides from structured_intent
        if structured_intent:
            overrides = structured_intent.get("template_variable_overrides", {})

            # Product version override
            if overrides.get("product_version"):
                variables["product_version"] = overrides["product_version"]
                logger.info(f"  Using product_version from structured_intent: {overrides['product_version']}")

            # Platform version override
            if overrides.get("platform_version"):
                variables["platform_version"] = overrides["platform_version"]
                logger.info(f"  Using platform_version from structured_intent: {overrides['platform_version']}")

            # Any other custom template variables
            for key, value in overrides.items():
                if key not in variables and value:
                    variables[key] = value
                    logger.info(f"  Using custom template variable from structured_intent: {key} = {value}")

        # Add product-specific variables from profile
        if hasattr(product_profile, 'global_config'):
            global_vars = product_profile.global_config.get("template_variables", {}).get("global", {})
        else:
            # Fallback for legacy profile structure
            profile_strategies = product_profile.get("generation_strategies", {}) if isinstance(product_profile, dict) else {}
            global_vars = profile_strategies.get("template_variables", {}).get("global", {})

        for var_name, var_def in global_vars.items():
            if var_name not in variables:
                # Check if required and not yet set
                variables[var_name] = f"[{var_name}]"

        # Apply structured_intent overrides for ALL template variables (final override)
        if structured_intent:
            overrides = structured_intent.get("template_variable_overrides", {})
            for key, value in overrides.items():
                if value:  # Only override if value is not empty
                    variables[key] = value
                    logger.info(f"  Applied template variable override: {key} = {value}")

        return variables

    async def _extract_template_variables_via_llm(
        self,
        knowledge_base: Dict[str, Any],
        known_vars: Dict[str, str],
    ) -> Dict[str, str]:
        """
        Stage B: Use the LLM to extract template variables that depend on
        the Document Analyzer's field-naming choices.

        Only fills keys that are still placeholders (contain '[').
        Merges the LLM's JSON output into known_vars and returns the enriched dict.
        """
        import json as _json

        # Compact representation of the document-derived knowledge — send enough for context (~8K chars)
        kb_text = _json.dumps(knowledge_base, indent=2, default=str)[:8000]

        # Build the list of variables still needing values
        missing = {k: v for k, v in known_vars.items() if "[" in str(v)}
        if not missing:
            return known_vars  # Nothing to fill

        fields_spec = "\n".join(
            f'  "{k}": "<{k.replace("_", " ")} — extract from uploaded documents>"'
            for k in missing
        )

        system_prompt = (
            "You are a metadata extraction specialist. "
            "Read the DocumentKnowledgeBase below and extract the requested fields. "
            "Return only valid JSON. For any field you cannot find, return null."
        )
        user_prompt = (
            f"Extract these template variable fields from the DocumentKnowledgeBase:\n"
            f"{{\n{fields_spec}\n}}\n\n"
            f"For platform_version: combine the cloud platform name and software version "
            f"(e.g. 'Nokia CBIS R22 for UPW / CBIS R24 for PJB on OpenStack Train').\n"
            f"For deployment_model: describe the architecture model "
            f"(e.g. 'Distributed virtualized with geo-redundant mated pairs').\n"
            f"For product_version: the main application software version "
            f"(e.g. 'DSR 9.0.2.0.0').\n\n"
            f"DocumentKnowledgeBase:\n{kb_text}\n\n"
            f"Return ONLY the JSON object. No prose."
        )

        try:
            result = await self.llm.chat_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=500,
                temperature=None,
            )
            if isinstance(result, dict):
                filled = 0
                for key, val in result.items():
                    if val is not None and str(val).strip() and key in known_vars:
                        known_vars[key] = str(val).strip()
                        filled += 1
                logger.info(f"  Stage B LLM filled {filled} template variable(s)")
            else:
                logger.warning("  Stage B LLM returned non-dict — keeping Stage A values")
        except Exception as e:
            logger.warning(f"  Stage B LLM extraction failed: {e} — keeping Stage A values")

        return known_vars

    def _extract_nf_list(
        self, products: Dict[str, Any], product_profile: Any
    ) -> List[str]:
        """
        Extract the list of Network Functions or product components.

        Reads from profile metadata instead of hardcoded lists for product-agnostic behavior.
        """
        nf_list = []

        # Get NF keywords from profile metadata (product-agnostic)
        if hasattr(product_profile, 'metadata'):
            target_nfs = product_profile.metadata.get("network_functions", [])
        else:
            # Fallback for dict-based profile
            metadata = product_profile.get("metadata", {}) if isinstance(product_profile, dict) else {}
            target_nfs = metadata.get("network_functions", [])

        if not target_nfs:
            logger.warning(f"No network_functions found in profile metadata, NF list will be empty")
            return []

        for prod_name, prod_info in products.items():
            if isinstance(prod_info, dict):
                components = prod_info.get("components", [])
            elif hasattr(prod_info, "components"):
                components = prod_info.components
            else:
                components = []

            for comp in components:
                # Use exact token matching to avoid substring false positives
                # e.g., "SCP" should not match "SCOPING"
                comp_upper = comp.upper().strip()
                comp_tokens = set(comp_upper.split())
                comp_tokens.update(comp_upper.replace("-", " ").split())
                comp_tokens.add(comp_upper)  # Also match the full component name
                for nf in target_nfs:
                    if nf in comp_tokens and nf not in nf_list:
                        nf_list.append(nf)

            # Also check product name itself (exact token match)
            prod_tokens = set(prod_name.upper().split())
            prod_tokens.update(prod_name.upper().replace("-", " ").split())
            for nf in target_nfs:
                if nf in prod_tokens and nf not in nf_list:
                    nf_list.append(nf)

        return nf_list

    async def _classify_deployment_type(self, knowledge_base: Dict[str, Any]) -> str:
        """
        Classify the deployment type using LLM analysis.

        Analyzes project overview, special notes, and other context to determine:
        - Greenfield: New installation from scratch
        - Upgrade: Upgrading existing system to new version
        - Project Expansion: Adding new components/capacity to existing deployment
        - Project Initiation: Initial planning/design phase before deployment

        Args:
            knowledge_base: DocumentKnowledgeBase as dict

        Returns:
            Deployment type classification string
        """
        # Extract relevant fields for classification
        project_overview = knowledge_base.get("project_overview", "")
        special_notes = knowledge_base.get("special_notes", [])
        products = knowledge_base.get("products", {})

        # Build context for LLM
        context_parts = []
        if project_overview:
            context_parts.append(f"Project Overview:\n{project_overview}")

        if special_notes:
            notes_text = "\n".join(f"- {note}" for note in special_notes if note)
            context_parts.append(f"\nSpecial Notes:\n{notes_text}")

        if products:
            product_names = list(products.keys())
            context_parts.append(f"\nProducts/Components: {', '.join(product_names)}")

        context = "\n\n".join(context_parts) if context_parts else "No project context available"

        # System prompt for classification
        system_prompt = """You are an expert IT Project Manager and Systems Architect. Your task is to analyze project documentation extracts and classify the deployment type into one of the comprehensive categories defined below.

Instructions:

Read the provided project documentation context carefully.

Analyze the text for indicators regarding the current state of infrastructure, the goal of the project, and the scope of work.

Select the single most accurate classification from the list below.

If the context contains elements of multiple types (e.g., an upgrade that also adds new sites), prioritize the dominant activity or classify it as "Hybrid/Complex" if the activities are equally weighted.

Classification Categories:

Greenfield Deployment

Definition: Brand new installation in an environment where no such system previously existed. Building from the ground up.

Key Indicators: "New site", "fresh installation", "from scratch", "no existing infrastructure", "initial setup", "greenfield", "first-time deployment".

Brownfield Deployment (Upgrade/Modernization)

Definition: Work performed on an existing legacy system. This includes upgrading software versions, replacing hardware while keeping configurations, or modernizing parts of a live system.

Key Indicators: "Upgrade", "migration", "legacy replacement", "version update", "refactor", "modernize", "retrofit", "replace existing".

Expansion (Scale-Out/Add-on)

Definition: Adding capacity or new features to a currently stable and active deployment. This does not fundamentally change the core existing version but extends its reach.

Key Indicators: "Add capacity", "new nodes", "additional licenses", "extend coverage", "add module", "scale out", "new branch office connection".

Consolidation/Rationalization

Definition: Merging multiple separate systems into a centralized one or reducing the footprint of an existing deployment to improve efficiency.

Key Indicators: "Merge", "centralize", "decommission", "reduce footprint", "unify", "standardize", "shut down redundant sites".

Proof of Concept (PoC) / Pilot

Definition: A limited, temporary, or experimental deployment designed to test feasibility before a full rollout.

Key Indicators: "Trial", "pilot phase", "test environment", "evaluation", "PoC", "lab test", "limited scope", "feasibility study".

Disaster Recovery (DR) / Redundancy

Definition: Deploying backup systems, failover sites, or high-availability clusters to ensure business continuity.

Key Indicators: "Failover site", "backup", "redundancy", "standby", "DR setup", "active-passive", "business continuity".

Hybrid/Complex

Definition: A project that significantly combines elements of multiple categories (e.g., a Greenfield deployment at a new site concurrent with a Brownfield upgrade at HQ).

Key Indicators: "Mixed scope", "multi-phase transformation", "simultaneous upgrade and expansion".

Response Format:
Respond with ONLY the classification category name (e.g., "Greenfield Deployment"). Do not provide explanations or extra text."""

        user_prompt = f"""Analyze the following project documentation and classify the deployment type:

{context}

Based on the above context, what is the deployment type? Respond with only one of: Greenfield, Upgrade, Project Expansion, or Project Initiation."""

        try:
            logger.info("  Calling LLM for deployment type classification...")
            result = await self.llm.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=50,
                temperature=0.0,
            )

            # Extract classification from response
            classification = result.strip()
            if not classification:
                # Retry once with a shorter direct prompt for models that occasionally return empty output.
                retry_prompt = (
                    "Classify deployment type as exactly one of: "
                    "Greenfield, Upgrade, Project Expansion, Project Initiation.\n\n"
                    f"Context:\n{context}"
                )
                retry_result = await self.llm.chat(
                    system_prompt="You are a telecom deployment classifier. Return one label only.",
                    user_prompt=retry_prompt,
                    max_tokens=32,
                    temperature=0.0,
                )
                classification = (retry_result or "").strip()

            # Validate response
            valid_types = ["Greenfield", "Upgrade", "Project Expansion", "Project Initiation"]
            if classification in valid_types:
                return classification

            # Try case-insensitive matching
            for valid_type in valid_types:
                if classification.lower() == valid_type.lower():
                    return valid_type

            # Fallback: try to find keyword match
            classification_lower = classification.lower()
            if "greenfield" in classification_lower or "green field" in classification_lower:
                return "Greenfield"
            elif "upgrade" in classification_lower or "migration" in classification_lower:
                return "Upgrade"
            elif "expansion" in classification_lower or "expand" in classification_lower:
                return "Project Expansion"
            elif "initiation" in classification_lower or "planning" in classification_lower:
                return "Project Initiation"

            # Heuristic fallback from source context if model output is empty/ambiguous.
            context_lower = context.lower()
            if "project initiation" in context_lower or "pid" in context_lower:
                return "Project Initiation"
            if "upgrade" in context_lower or "migration" in context_lower:
                return "Upgrade"
            if "expand" in context_lower or "expansion" in context_lower:
                return "Project Expansion"

            # Default fallback
            logger.warning(f"  Could not parse LLM classification: '{classification}', defaulting to 'Greenfield'")
            return "Greenfield"

        except Exception as e:
            logger.error(f"  Deployment type classification failed: {e}")
            # Safe fallback
            return "Greenfield"
