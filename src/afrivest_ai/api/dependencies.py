from fastapi import Request
from afrivest_ai.core.agent import AgentBundle

def get_agent_bundle(request: Request) -> AgentBundle:
    """Dependency to inject the AgentBundle from the app state."""
    return request.app.state.agent_bundle
