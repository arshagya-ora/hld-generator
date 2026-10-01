"""
LLM Helper for Document Analyzer Agent.

Provides intelligent query generation and Cognee result interpretation using OCI GenAI.
This enables the agent to be truly adaptive and intelligent by:
1. Generating smart queries based on document discoveries
2. Interpreting Cognee knowledge graph results into structured data
3. Making follow-up queries based on previous results
"""

from typing import Dict, Any, List, Optional, Type
import json
import re
from pydantic import BaseModel

from hld_generator.external.oci_adapters import OCILLMAdapter, OCIConfig
from hld_generator.shared.logging_config import setup_logger

logger = setup_logger(__name__)


class LLMHelper:
    """
    LLM Helper for intelligent document analysis.

    Uses OCI GenAI to:
    - Analyze Cognee results and understand document content
    - Generate intelligent follow-up queries
    - Parse Cognee responses into structured Pydantic models
    """

    def __init__(self, config: Optional[OCIConfig] = None):
        """Initialize LLM helper with OCI GenAI client"""
        self.llm = OCILLMAdapter(config=config)
        logger.info(f"LLM Helper initialized with model: {self.llm.model}")

    async def interpret_discovery_results(
        self,
        cognee_results: List[Any],
        query: str
    ) -> Dict[str, Any]:
        """
        Interpret Cognee discovery results using LLM.

        Args:
            cognee_results: Raw results from Cognee search
            query: The original query that produced these results

        Returns:
            Structured interpretation with extracted insights
        """
        # Combine Cognee results into context
        context = self._format_cognee_results(cognee_results)

        prompt = f"""You are analyzing results from a knowledge graph search about a document.

Original Query: {query}

Knowledge Graph Results:
{context}

Based on these results, extract:
1. What type of document is this? (PID, RFP, Technical Spec, Upgrade Plan, etc.)
2. Who is the customer/client? Look for company names, customer identifiers, or "for <Company>" patterns.
3. What is the project name or project identifier?
4. What primary products or systems is this document about? (e.g., "Diameter Routing Server", "Nokia CBIS")
5. What topics/sections does the document cover?

Return your analysis as JSON with this structure:
{{
  "document_type": "...",
  "customer": "..." or null,
  "project_name": "..." or null,
  "primary_products": ["Product A", "Product B"],
  "topics_covered": ["topic1", "topic2"],
  "confidence": 0.0 to 1.0
}}

Be precise. Extract exact names as they appear in the document. Use null for genuinely missing fields.
"""

        messages = [
            {"role": "system", "content": "You are a technical document analysis expert. Extract information precisely and return valid JSON."},
            {"role": "user", "content": prompt}
        ]

        try:
            response = await self.llm.create_chat_completion(
                messages=messages,
                max_tokens=1000
            )

            # Parse JSON response (strip markdown code blocks if present)
            result = json.loads(self._extract_json_from_response(response))
            logger.info(f"LLM interpreted discovery: {result.get('document_type', 'Unknown')}")

            # DEBUG: Log extracted values to trace caching
            logger.info(f"🔍 LLM DEBUG: customer={result.get('customer', 'N/A')}")
            logger.info(f"🔍 LLM DEBUG: project_name={result.get('project_name', 'N/A')}")
            logger.info(f"🔍 LLM DEBUG: primary_products={result.get('primary_products', [])}")

            return result

        except Exception as e:
            logger.error(f"Error interpreting discovery results: {e}")
            return {
                "document_type": "Unknown",
                "customer": None,
                "project_name": None,
                "topics_covered": [],
                "confidence": 0.5
            }

    async def generate_adaptive_queries(
        self,
        document_intelligence: Dict[str, Any],
        discovered_topics: List[str],
        selected_product_name: str
    ) -> List[Dict[str, str]]:
        """
        Generate intelligent follow-up queries based on discoveries.

        Args:
            document_intelligence: Results from discovery phase
            discovered_topics: Topics found in document
            selected_product_name: Product name pre-selected by user

        Returns:
            List of query dictionaries with category, query, and priority
        """
        prompt = f"""You are generating intelligent queries to extract information from a knowledge graph about a document.

Document Intelligence:
- Type: {document_intelligence.get('document_type', 'Unknown')}
- Customer: {document_intelligence.get('customer', 'Unknown')}
- Project: {document_intelligence.get('project_name', 'Unknown')}
- Selected Product: {selected_product_name}
- Topics: {', '.join(discovered_topics)}

IMPORTANT: The user has pre-selected "{selected_product_name}" as the product of interest.
All product-related queries MUST focus ONLY on extracting details about "{selected_product_name}".

Generate 15-20 specific, single-focused queries to extract:

1. **Project Overview**: Scope, objectives, business drivers, deliverables
2. **Product Details for {selected_product_name}**:
   - Purpose and capabilities
   - Version/release information
   - Architecture and design
   - Components and sub-systems
   - Interfaces (S6a, Gx, Gy, etc.)
   - IP addresses, VLANs, network details
   - Configuration details
3. **Deployment Info**: Sites, locations, deployment model, topology for {selected_product_name}
4. **Capacity/Sizing**: Subscriber counts, TPS, VM requirements, dimensioning for {selected_product_name}
5. **Network/Integration**: Interfaces, protocols, existing systems for {selected_product_name}
6. **Timeline**: Milestones, phases, project schedule
7. **Infrastructure**: Cloud platform, hardware, deployment model
8. **Diagrams**: Architecture diagrams, topology diagrams showing {selected_product_name}
9. **Tables**: BOQ, capacity tables, VM specs, resource tables for {selected_product_name}
10. **Special Requirements**: Compliance, constraints, special instructions

CRITICAL RULES:
- Each query MUST ask ONE focused question only (NO multi-part questions)
- Each query MUST end with: "Return answer as structured JSON."
- Product queries MUST specifically mention "{selected_product_name}"
- Focus on DETAILS (version, components, interfaces, IPs) not just generic info
- Prioritize queries about diagrams and tables (they contain the most important details)

GOOD examples:
- "What is the version of {selected_product_name}? Return answer as structured JSON."
- "What are the components/modules of {selected_product_name}? Return answer as structured JSON."
- "List all interfaces (S6a, Gx, etc.) configured for {selected_product_name}. Return answer as structured JSON."
- "What are the IP addresses and VLANs for {selected_product_name}? Return answer as structured JSON."
- "Extract all architecture diagrams showing {selected_product_name}. Return answer as structured JSON."
- "Extract all BOQ tables and resource tables for {selected_product_name}. Return answer as structured JSON."

BAD examples:
- "What products are mentioned?" (DON'T discover products - we already know it's {selected_product_name})
- "List all products" (NO - only {selected_product_name} matters)

Return as JSON array:
[
  {{
    "category": "project_overview",
    "query": "What is the project scope? Return answer as structured JSON.",
    "priority": "high"
  }},
  {{
    "category": "products",
    "query": "What is the purpose and functionality of {selected_product_name}? Return answer as structured JSON.",
    "priority": "high"
  }},
  {{
    "category": "products",
    "query": "What version/release of {selected_product_name} is being deployed? Return answer as structured JSON.",
    "priority": "high"
  }},
  ...
]
"""

        messages = [
            {"role": "system", "content": "You are an expert at generating intelligent queries for knowledge graph extraction. Generate precise, targeted queries."},
            {"role": "user", "content": prompt}
        ]

        try:
            response = await self.llm.create_chat_completion(
                messages=messages,
                max_tokens=2000
            )

            queries = json.loads(self._extract_json_from_response(response))
            if not isinstance(queries, list):
                logger.warning("LLM returned non-list for queries, wrapping in list")
                queries = [queries] if queries else []
            logger.info(f"LLM generated {len(queries)} adaptive queries")
            return queries

        except Exception as e:
            logger.error(f"Error generating queries: {e}")
            return []

    async def parse_cognee_results_to_structure(
        self,
        cognee_results: List[Any],
        query: str,
        target_model: Type[BaseModel]
    ) -> List[Dict[str, Any]]:
        """
        Parse Cognee results into structured Pydantic model data using LLM.

        Args:
            cognee_results: Raw Cognee search results
            query: The query that produced these results
            target_model: Pydantic model class to extract into

        Returns:
            List of dictionaries matching the target model schema
        """
        context = self._format_cognee_results(cognee_results)
        schema = target_model.model_json_schema()

        prompt = f"""You are parsing knowledge graph results into structured data.

Query: {query}

Knowledge Graph Results:
{context}

Extract information and return as JSON array matching this schema:
{json.dumps(schema, indent=2)}

Rules:
- Extract all relevant instances (e.g., if multiple sites, return multiple objects)
- Use null for missing/unknown fields
- Extract COMPLETE information, DO NOT fragment names into individual words
  - GOOD: "Diameter Routing Server", "Bangalore Primary DC"
  - BAD: "Diameter", "Routing", "Server" as separate entries
- DO NOT create separate entries for each word in a multi-word name
- Reject single-word fragments - only extract complete entity names (2+ words for products)
- Be precise and accurate
- If results are empty or irrelevant, return empty array []

Return ONLY valid JSON array, nothing else.
"""

        messages = [
            {"role": "system", "content": "You are a data extraction expert. Parse information precisely into structured JSON."},
            {"role": "user", "content": prompt}
        ]

        try:
            response = await self.llm.create_chat_completion(
                messages=messages,
                max_tokens=2000
            )

            # Parse JSON response (strip markdown code blocks if present)
            extracted = json.loads(self._extract_json_from_response(response))

            # Ensure it's a list
            if isinstance(extracted, dict):
                extracted = [extracted]

            # Validate and filter out fragmented entries
            validated = []
            for item in extracted:
                # Check if this is a ProductInfo and validate the name
                if target_model.__name__ == "ProductInfo" and isinstance(item, dict):
                    name = item.get("name", "")
                    # Reject single-word product names (likely fragments)
                    if name and len(name.split()) >= 2:
                        validated.append(item)
                    elif name and len(name.split()) == 1:
                        logger.warning(f"Rejecting fragmented product name: '{name}' (single word)")
                else:
                    # For non-Product models, accept all valid entries
                    validated.append(item)

            logger.info(f"LLM extracted {len(validated)} valid {target_model.__name__} instances (rejected {len(extracted) - len(validated)} fragments)")
            return validated

        except Exception as e:
            logger.error(f"Error parsing Cognee results: {e}")
            return []

    async def extract_simple_field(
        self,
        cognee_results: List[Any],
        field_name: str,
        field_description: str
    ) -> Any:
        """
        Extract a single field value from Cognee results.

        Args:
            cognee_results: Raw Cognee results
            field_name: Name of field to extract
            field_description: Description of what to extract

        Returns:
            Extracted value (string, number, list, etc.)
        """
        context = self._format_cognee_results(cognee_results)

        prompt = f"""Extract the following field from knowledge graph results:

Field: {field_name}
Description: {field_description}

Knowledge Graph Results:
{context}

Return as JSON:
{{
  "{field_name}": <extracted value>
}}

Use null if not found. Be precise.
"""

        messages = [
            {"role": "system", "content": "You are a data extraction expert."},
            {"role": "user", "content": prompt}
        ]

        try:
            response = await self.llm.create_chat_completion(
                messages=messages,
                max_tokens=500
            )

            result = json.loads(self._extract_json_from_response(response))
            return result.get(field_name)

        except Exception as e:
            logger.error(f"Error extracting field {field_name}: {e}")
            return None

    async def interpret_category_results(
        self,
        category_name: str,
        all_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Interpret all results for a category and extract structured information.

        Args:
            category_name: Category (e.g., "deployment", "capacity")
            all_results: All query results for this category

        Returns:
            Structured dictionary with extracted information
        """
        # Combine all results for this category
        combined_context = []
        for result in all_results:
            if result.get("success"):
                query = result.get("query", "")
                cognee_results = result.get("results", [])
                formatted = self._format_cognee_results(cognee_results)
                combined_context.append(f"Query: {query}\nResults:\n{formatted}\n")

        context = "\n---\n".join(combined_context)

        # Extract product name from category if it's a product-specific category
        is_product_category = "product" in category_name.lower()
        product_focus_note = ""
        if is_product_category and "_for_" in category_name:
            # Category like "product_details_for_Diameter Routing Server"
            product_name = category_name.split("_for_", 1)[1] if "_for_" in category_name else ""
            product_focus_note = f"\n\nIMPORTANT: Focus ONLY on information about {product_name}. Ignore other products or systems."

        # Build a category-specific schema hint so the LLM returns consistently
        # structured data that the synthesis methods can reliably map.
        schema_hints = {
            "project_overview": '{"scope": "...", "objectives": ["..."], "business_drivers": ["..."], "deliverables": ["..."]}',
            "deployment_plan":  '{"approach": "...", "phases": ["..."], "deployment_sequence": ["..."], "sites": [{"name": "...", "location": "...", "role": "..."}]}',
            "deployment_sites": '{"sites": [{"name": "...", "location": "...", "type": "primary|DR|edge", "role": "...", "components": ["..."]}]}',
            "capacity_and_sizing": '{"subscribers": "...", "peak_tps": "...", "concurrent_sessions": "...", "vm_requirements": {"VM_type": {"vcpu": N, "ram_gb": N, "storage_gb": N}}, "dimensioning_basis": "...", "growth_projections": "..."}',
            "network_and_integration": '{"interfaces": ["S6a", "Gx", "Gy", "..."], "protocols": ["Diameter", "..."], "network_segments": ["..."], "existing_systems": ["..."], "ip_plan": "..."}',
            "infrastructure": '{"platform": "...", "cloud_platform": "Nokia CBIS / OpenStack / ...", "deployment_model": "...", "hardware": "...", "versions": "..."}',
            "timeline_and_milestones": '{"project_start": "...", "milestones": [{"name": "...", "date": "...", "description": "..."}]}',
        }
        # Match by prefix for product-specific categories
        schema_hint = ""
        for key, hint in schema_hints.items():
            if key in category_name.lower() or category_name.lower().startswith(key.split("_")[0]):
                schema_hint = f"\n\nReturn JSON matching this structure:\n{hint}"
                break

        prompt = f"""Interpret knowledge graph results for the "{category_name}" category.

All Results:
{context}
{product_focus_note}

Extract ALL details related to {category_name}. Be thorough — include specific numbers,
version strings, component names, IP addresses, VLAN IDs, TPS/MPS figures, VM specs,
site names and locations, interface names, and any other concrete technical details present.
{schema_hint}

Rules:
- Return comprehensive JSON with all extracted information
- Include specific numeric values (e.g., "300K MPS", "31 VMs", "372 vCPU")
- Do NOT fragment product/system names — keep full names like "Diameter Routing Server 9.0.2"
- If a field is not mentioned in the results, omit it or set to null
- Prefer structured lists over long prose for components, sites, phases, etc.
"""

        messages = [
            {"role": "system", "content": f"You are analyzing {category_name} information from a technical document."},
            {"role": "user", "content": prompt}
        ]

        try:
            response = await self.llm.create_chat_completion(
                messages=messages,
                max_tokens=1500
            )

            result = json.loads(self._extract_json_from_response(response))
            logger.info(f"LLM interpreted {category_name} category")
            return result

        except Exception as e:
            logger.error(f"Error interpreting category {category_name}: {e}")
            return {}

    async def extract_full_knowledge_base(
        self,
        document_text: str,
        selected_product_name: str,
        doc_intelligence_hint: dict = None,
    ) -> dict:
        """
        Extract the complete DocumentKnowledgeBase from raw document text.

        Sends up to 40 000 chars of the parsed document directly to the LLM and
        asks it to return the full structured JSON in one pass.  This avoids the
        quality loss that comes from Cognee chunking + RAG retrieval.

        Args:
            document_text: Full (or truncated) parsed document text.
            selected_product_name: The product the user is interested in.
            doc_intelligence_hint: Optional dict from the discovery phase with
                                   document_type / customer / project_name hints.

        Returns:
            Dict matching DocumentKnowledgeBase fields (may be partial).
        """
        hint_block = ""
        if doc_intelligence_hint:
            hint_block = (
                f"\nKnown context (from prior analysis):\n"
                f"  Document type : {doc_intelligence_hint.get('document_type', '?')}\n"
                f"  Customer      : {doc_intelligence_hint.get('customer', '?')}\n"
                f"  Project       : {doc_intelligence_hint.get('project_name', '?')}\n"
            )

        prompt = f"""You are a senior technical document analyst. Extract every relevant detail from the document below and return it as structured JSON.

Product of Interest: {selected_product_name}
{hint_block}
=== DOCUMENT TEXT (start) ===
{document_text}
=== DOCUMENT TEXT (end) ===

CRITICAL: Customer Name Extraction
When extracting the customer name, look for:
1. Explicit "Customer:" or "Client:" statements in headers/title pages
2. Company names in document titles (e.g., "XYZ Corp - HLD")
3. Consistent organization names mentioned throughout the document
4. Common telecommunication operator abbreviations:
   - STC → Saudi Telecom Company
   - VIL → Vodafone Idea Limited
   - TCL → Telecom Company Limited
   - If you see an abbreviation with context suggesting it's the customer, preserve the abbreviation

DO NOT use as customer name:
- Vendor names (Nokia, Ericsson, etc.) - these are suppliers, not customers
- Generic placeholders like "Solutions by...", "[Customer Name]", "Company X"
- Document author names or project team member names

If the customer name is genuinely uncertain, prefer using the abbreviation over inventing a full name.

Return ONLY a single JSON object with these exact top-level keys.
Fill every field you can find; use null / [] for genuinely missing data.

{{
  "document_intelligence": {{
    "document_type": "PID / RFP / Technical Spec / Upgrade Plan / ...",
    "customer": "extracted customer/operator name (or null if not found)",
    "project_name": "...",
    "primary_products": ["..."],
    "document_sections": ["1. Introduction", "2. Architecture", "3. Deployment Plan", "..."],
    "confidence": 0.9
  }},
  "project_overview": {{
    "scope": "complete scope description",
    "objectives": ["objective 1", "..."],
    "business_drivers": ["driver 1", "..."],
    "deliverables": ["deliverable 1", "..."]
  }},
  "products": {{
    "{selected_product_name}": {{
      "name": "{selected_product_name}",
      "purpose": "...",
      "version": "...",
      "architecture": "...",
      "components": ["NOAM", "SOAM", "DA-MP", "..."],
      "deployment_model": "...",
      "interfaces": ["S6a", "Gx", "Gy", "Cx", "..."]
    }}
  }},
  "sites": [
    {{
      "name": "site name",
      "location": "city / country",
      "site_type": "primary / DR / edge",
      "role": "what this site does",
      "deployed_components": ["component list"],
      "capacity": "e.g. '300K MPS per instance, 30Mn sessions' or null"
    }}
  ],
  "capacity_and_sizing": {{
    "subscribers": "e.g. 5 million",
    "peak_tps": "e.g. 300K MPS / 150K TPS",
    "concurrent_sessions": "...",
    "vm_requirements": {{
      "NOAM": {{"vcpu": 8, "ram_gb": 16, "storage_gb": 100}},
      "SOAM": {{"vcpu": 4, "ram_gb": 8, "storage_gb": 50}}
    }},
    "hardware_specs": {{}},
    "dimensioning_basis": "...",
    "growth_projections": "..."
  }},
  "network_and_integration": {{
    "interfaces": ["S6a", "Gx", "Gy", "Cx", "Sh", "Rx", "..."],
    "protocols": ["Diameter", "RADIUS", "HTTP/2", "..."],
    "network_segments": ["management VLAN", "signaling VLAN", "..."],
    "existing_systems": ["MME", "PGW", "HSS", "PCRF", "..."],
    "ip_plan": "any IP addressing details"
  }},
  "deployment_plan": {{
    "approach": "high-level description of deployment strategy",
    "phases": ["Phase 1: ...", "Phase 2: ..."],
    "deployment_sequence": ["step 1", "step 2", "..."]
  }},
  "infrastructure": {{
    "platform": "Nokia CBIS / OpenStack / AWS / ...",
    "cloud_platform": "exact platform name + version",
    "hardware": "HPE G10 / Dell / ...",
    "deployment_model": "active-standby HA / geo-redundant / ...",
    "versions": "platform versions and compatibility"
  }},
  "timeline": {{
    "project_start": "YYYY-MM-DD format (extract from document date/kickoff date) or null",
    "milestones": [
      {{"name": "Milestone 1", "date": "YYYY-MM-DD or null", "description": "exact description from document"}}
    ]
  }},
  "special_notes": [
    "important constraint or requirement 1",
    "compliance or interoperability note 2"
  ]
}}

Rules:
- Extract EXACT values: version strings, vCPU counts, subscriber numbers, site names
- For document_sections: extract main sections from the Table of Contents or numbered headings (e.g. "1. Introduction", "2. Deployment Details")
- For project_start: look for document date, project kickoff date, or release date - convert to YYYY-MM-DD format
- For milestones: extract actual milestone descriptions from the document, not generic summaries
- For sites capacity: extract per-site TPS/MPS capacity and session limits where mentioned
- List ALL interfaces (S6a, Gx, Gy, Cx, Sh, Rx, etc.) explicitly found in the text
- List ALL VM types with their resource specs where mentioned
- List ALL sites with their geographic locations and roles
- Keep product names complete (e.g. "Diameter Routing Server 9.0.2", not just "DSR")
- Include any upgrade/migration notes, compliance constraints, or SIEM requirements
- If a section of the document describes figures or diagrams, note them in special_notes
"""

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert at extracting structured technical information "
                    "from telecom deployment documents. Be thorough and precise. "
                    "Return only valid JSON — no markdown, no explanation."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        try:
            # 8000 tokens for output — the full knowledge-base JSON for a
            # typical 20-30 page RD is 4000-6000 tokens; 4000 was too small
            # and caused silent truncation + JSON parse failure → empty result.
            response = await self.llm.create_chat_completion(
                messages=messages,
                max_tokens=20000,
            )
            raw = self._extract_json_from_response(response)
            result = json.loads(raw)
            logger.info("Full knowledge-base extraction succeeded")
            return result
        except json.JSONDecodeError as e:
            logger.error(f"Full knowledge-base extraction: JSON parse failed — {e}")
            logger.debug(f"Raw LLM response (first 500 chars): {response[:500] if response else 'empty'}")
            return {}
        except Exception as e:
            logger.error(f"Full knowledge-base extraction failed: {e}")
            return {}

    def _extract_json_from_response(self, response: str) -> str:
        """
        Extract JSON from an LLM response that may contain markdown code blocks.

        Handles patterns like:
          ```json\n[...]\n```
          ```\n{...}\n```
          or raw JSON
        """
        if not response:
            return response
        # Strip markdown code fences (```json ... ``` or ``` ... ```)
        code_block = re.search(r'```(?:json)?\s*([\s\S]*?)```', response)
        if code_block:
            return code_block.group(1).strip()
        # Try to find outermost JSON array or object
        json_match = re.search(r'(\[[\s\S]*\]|\{[\s\S]*\})', response)
        if json_match:
            return json_match.group(1)
        return response.strip()

    def _format_cognee_results(self, results: List[Any]) -> str:
        """Format Cognee results into readable text for LLM"""
        if not results:
            return "(No results found)"

        formatted_parts = []
        for i, result in enumerate(results[:10], 1):  # Limit to top 10
            if isinstance(result, str):
                formatted_parts.append(f"{i}. {result}")
            elif isinstance(result, dict):
                # Extract text from various possible fields
                text = (
                    result.get("text", "") or
                    result.get("content", "") or
                    result.get("snippet", "") or
                    str(result)
                )
                formatted_parts.append(f"{i}. {text}")
            else:
                formatted_parts.append(f"{i}. {str(result)}")

        return "\n".join(formatted_parts)

    async def batch_generate_table_descriptions(
        self,
        tables: List[Dict[str, Any]],
        chunks: List[Any] = None
    ) -> List[str]:
        """
        Generate descriptions for all tables in a single batched LLM call.

        Args:
            tables: List of table dicts with 'section', 'markdown', 'page_number'
            chunks: Optional list of semantic chunks to extract table context

        Returns:
            List of description strings (one per table)
        """
        if not tables:
            return []

        # Build table blocks with context
        table_blocks = []
        for i, table in enumerate(tables):
            section = table.get("section", "Unknown section")
            page = table.get("page_number", "?")
            markdown = table.get("markdown", "")[:600]  # Limit to 600 chars

            # Try to find context from chunks
            context = ""
            if chunks:
                context = self._find_table_context(chunks, section, markdown[:200])

            block = (
                f"TABLE {i + 1} | Section: \"{section}\" | Page: {page}\n"
                f"Content excerpt:\n{markdown}"
            )

            if context:
                block += f"\nContext from document: {context[:300]}"

            table_blocks.append(block)

        # Build prompt
        prompt = f"""You are analyzing tables from a technical document.
For each table below, provide a concise description (15-30 words) explaining:
- What data the table contains
- The table's purpose or significance

Return ONLY a JSON array with one description string per table (in order).

{chr(10).join(f"=== {block} ===" for block in table_blocks)}

Example output format:
["Description for table 1", "Description for table 2", ...]

JSON array:"""

        try:
            response = await self._chat(prompt, max_tokens=2000)
            descriptions_json = self._extract_json_from_response(response)

            if not descriptions_json:
                logger.warning("LLM returned no JSON for table descriptions")
                return [""] * len(tables)

            descriptions = json.loads(descriptions_json)

            if isinstance(descriptions, list) and len(descriptions) == len(tables):
                return descriptions
            else:
                logger.warning(
                    f"LLM returned {len(descriptions)} descriptions but expected {len(tables)}, "
                    "padding with empty strings"
                )
                return descriptions + [""] * (len(tables) - len(descriptions))

        except Exception as e:
            logger.warning(f"Table description generation failed: {e}, returning empty descriptions")
            return [""] * len(tables)

    def _find_table_context(
        self,
        chunks: List[Any],
        section: str,
        table_preview: str
    ) -> str:
        """Find contextual text surrounding a table from semantic chunks."""
        # Try to find chunk that contains this table's section
        section_lower = section.lower().strip()

        for chunk in chunks:
            metadata = getattr(chunk, "metadata", {})
            chunk_section = metadata.get("section_title", "").lower().strip()

            if chunk_section and section_lower in chunk_section:
                # Found the chunk, extract context near table
                chunk_text = getattr(chunk, "text", "")

                # Look for table preview in chunk
                if table_preview[:50] in chunk_text:
                    # Find surrounding text
                    idx = chunk_text.find(table_preview[:50])
                    start = max(0, idx - 250)
                    end = min(len(chunk_text), idx + 250)
                    return chunk_text[start:end].replace("\n", " ").strip()

                # Fallback: return first 500 chars of chunk
                return chunk_text[:500].replace("\n", " ").strip()

        return ""
