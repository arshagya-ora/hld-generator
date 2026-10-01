from .base import BaseGenerationStrategy
from .hybrid_strategy import HybridStrategy

# Legacy aliases — all sections now use HybridStrategy exclusively.
# Kept so any external code referencing these names won't break.
TemplateStrategy = HybridStrategy
RAGStrategy = HybridStrategy
GeneratedStrategy = HybridStrategy

__all__ = [
    "BaseGenerationStrategy",
    "HybridStrategy",
    "TemplateStrategy",
    "RAGStrategy",
    "GeneratedStrategy",
]
