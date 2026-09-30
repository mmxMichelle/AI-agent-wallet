"""Compatibility entry point for the local stateful agent; no inference transport."""
from .agent_loop import Assessment, LocalAgent

GovernedAgent = LocalAgent
