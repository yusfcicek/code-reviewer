"""Adapters onto the code forge that hosts merge requests."""

from .client import MissingCredentialsError, build_gitlab_client

__all__ = ["build_gitlab_client", "MissingCredentialsError"]
