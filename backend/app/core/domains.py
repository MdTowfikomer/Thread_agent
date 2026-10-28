"""Compatibility entry point; workspace configuration has one persistent owner."""
from app.core.organizations import get_workspace

def get_domain(domain_id: str):
    return get_workspace(domain_id)
