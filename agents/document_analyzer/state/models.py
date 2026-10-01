"""
Pydantic models for Document Analyzer Agent output.

These models define the structured knowledge base extracted from documents.
They ensure type safety and provide validation for the agent's output.
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Union


class ProductInfo(BaseModel):
    """Information about a product/system mentioned in the document"""
    
    name: str = Field(..., description="Product or system name")
    purpose: Optional[str] = Field(None, description="What this product does")
    version: Optional[str] = Field(None, description="Version or release")
    architecture: Optional[str] = Field(None, description="High-level architecture description")
    components: List[str] = Field(default_factory=list, description="Sub-components or modules")
    deployment_model: Optional[str] = Field(None, description="How it's deployed")
    interfaces: List[str] = Field(default_factory=list, description="Integration interfaces")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "OC-DSR",
                "purpose": "Diameter signaling router for 5G core",
                "version": "9.1.0",
                "architecture": "Active-standby HA configuration",
                "components": ["Signaling VMs", "Management VMs", "Database"],
                "deployment_model": "Distributed across 3 sites",
                "interfaces": ["S6a", "Gx", "Gy"]
            }
        }


class SiteInfo(BaseModel):
    """Information about a deployment site"""
    
    name: str = Field(..., description="Site name or identifier")
    location: Optional[str] = Field(None, description="Geographic location")
    site_type: Optional[str] = Field(None, description="Type: primary, DR, edge, etc.")
    role: Optional[str] = Field(None, description="Site's role in deployment")
    deployed_components: List[str] = Field(default_factory=list, description="What gets deployed here")
    capacity: Optional[str] = Field(None, description="Site capacity information")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Bangalore Primary DC",
                "location": "Bangalore, India",
                "site_type": "primary",
                "role": "Active DSR instance",
                "deployed_components": ["DSR Active", "DB Primary"],
                "capacity": "5M subscribers"
            }
        }


class CapacityInfo(BaseModel):
    """Capacity and sizing information"""

    subscribers: Optional[Union[str, Dict[str, Any]]] = Field(None, description="Subscriber count (can be string or dict for site-specific data)")
    peak_tps: Optional[Union[str, Dict[str, Any]]] = Field(None, description="Peak transactions per second (can be string or dict for site-specific data)")
    concurrent_sessions: Optional[Union[str, Dict[str, Any]]] = Field(None, description="Concurrent sessions (can be string or dict for site-specific data)")
    vm_requirements: Dict[str, Any] = Field(default_factory=dict, description="VM resource specifications")
    hardware_specs: Dict[str, Any] = Field(default_factory=dict, description="Hardware requirements")
    dimensioning_basis: Optional[Union[str, Dict[str, Any]]] = Field(None, description="Basis for capacity planning (can be string or dict for site-specific data)")
    growth_projections: Optional[Union[str, Dict[str, Any]]] = Field(None, description="Expected growth (can be string or dict for site-specific data)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "subscribers": "5 million",
                "peak_tps": "50,000",
                "concurrent_sessions": "500,000",
                "vm_requirements": {
                    "DSR_VM": {"vcpu": 8, "ram_gb": 32, "storage_gb": 500}
                },
                "dimensioning_basis": "20% overhead for growth"
            }
        }


class DocumentIntelligence(BaseModel):
    """High-level document understanding"""
    
    document_type: str = Field(..., description="PID, RFP, Technical Spec, etc.")
    customer: Optional[str] = Field(None, description="Customer/client name")
    project_name: Optional[str] = Field(None, description="Project identifier")
    primary_products: List[str] = Field(default_factory=list, description="Main products discussed")
    document_sections: List[str] = Field(default_factory=list, description="Major sections in document")
    confidence_score: float = Field(1.0, ge=0.0, le=1.0, description="Analysis confidence 0-1")


class DocumentKnowledgeBase(BaseModel):
    """
    Complete structured knowledge extracted from a document.
    
    This is the primary output of the Document Analyzer Agent.
    It provides a comprehensive, queryable representation of project information.
    """
    
    # Document understanding
    document_intelligence: DocumentIntelligence = Field(
        ..., 
        description="What type of document this is and basic metadata"
    )
    
    # Project overview
    project_overview: Dict[str, Any] = Field(
        default_factory=dict,
        description="Scope, objectives, deliverables, business drivers"
    )
    
    # Products and systems
    products: Dict[str, ProductInfo] = Field(
        default_factory=dict,
        description="Products/systems indexed by name"
    )
    
    # Deployment sites
    sites: List[SiteInfo] = Field(
        default_factory=list,
        description="All deployment locations"
    )
    
    # Capacity and sizing
    capacity_and_sizing: Optional[CapacityInfo] = Field(
        None,
        description="Capacity requirements and sizing details"
    )
    
    # Network and integration
    network_and_integration: Dict[str, Any] = Field(
        default_factory=dict,
        description="Interfaces, protocols, network segments, existing systems"
    )
    
    # Deployment plan
    deployment_plan: Dict[str, Any] = Field(
        default_factory=dict,
        description="Deployment approach, phases, timeline, sequence"
    )
    
    # Infrastructure
    infrastructure: Dict[str, Any] = Field(
        default_factory=dict,
        description="Cloud platform, deployment model, hardware, network architecture"
    )
    
    # Timeline
    timeline: Dict[str, Any] = Field(
        default_factory=dict,
        description="Project start, milestones, deadlines"
    )
    
    # Diagrams and visual content
    diagrams: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Architecture diagrams, topology, etc."
    )
    
    # Tables and structured data
    tables: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="BOQ, resource tables, capacity tables, etc."
    )
    
    # Special notes
    special_notes: List[str] = Field(
        default_factory=list,
        description="Important constraints, requirements, compliance needs"
    )
    
    # Knowledge graph stats (from Cognee)
    knowledge_graph_stats: Dict[str, Any] = Field(
        default_factory=dict,
        description="Entity counts, relationship counts, completeness score"
    )
    
    # Extraction metadata
    extraction_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Query count, coverage, ambiguous items, missing info"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "document_intelligence": {
                    "document_type": "Project Initiation Document",
                    "customer": "Vodafone Idea",
                    "project_name": "OC-DSR 5G Core Deployment",
                    "primary_products": ["OC-DSR", "OpenStack"],
                    "document_sections": ["Introduction", "Scope", "Architecture"],
                    "confidence_score": 0.95
                },
                "products": {
                    "OC-DSR": {
                        "name": "OC-DSR",
                        "purpose": "Diameter signaling router",
                        "version": "9.1.0"
                    }
                }
            }
        }
