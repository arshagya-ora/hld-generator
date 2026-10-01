"""
Blueprint Agent package.

The Blueprint Agent transforms DocumentKnowledgeBase + ImageInventory
into a complete HLD generation plan (BlueprintOutput).

Usage:
    from hld_generator.agents.blueprint import BlueprintAgent

    agent = BlueprintAgent()
    blueprint = await agent.run(knowledge_base_dict)
"""

__all__ = ["BlueprintAgent"]


def __getattr__(name):
    if name == "BlueprintAgent":
        from .agent import BlueprintAgent

        return BlueprintAgent
    raise AttributeError(name)
