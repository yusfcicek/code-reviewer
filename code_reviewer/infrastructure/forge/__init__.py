"""Adapters onto the code forge that hosts merge requests."""

from .gitlab_client import MissingCredentialsError, build_gitlab_client

__all__ = ["MissingCredentialsError", "build_gitlab_client"]
