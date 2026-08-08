"""In-memory stand-ins for the things a review talks to."""

from .scripted_model import ScriptedChatModel, hermes_call

__all__ = ["ScriptedChatModel", "hermes_call"]
