"""GitLab client construction.

Kept separate from the orchestration so the connection policy — credentials and
TLS in particular — can be asserted in a unit test without a live instance.

The client used to be built with ``ssl_verify=False`` hard-coded, silently
accepting any certificate for every request that carries ``GITLAB_TOKEN``
(finding F-20). Verification is now on unless an operator turns it off in the
environment, and turning it off is noisy.
"""

import os
import warnings
from typing import Union

import gitlab

#: Values accepted as "yes, really disable certificate verification".
_FALSEY = {"false", "0", "no", "off"}
_TRUTHY = {"true", "1", "yes", "on"}


class MissingCredentialsError(RuntimeError):
    """Raised when the GitLab URL or token is absent.

    The previous code only printed a warning and continued, so a missing token
    surfaced later as an opaque 401 in the middle of a review.
    """


def resolve_ssl_verify() -> Union[bool, str]:
    """Decides what to pass as ``ssl_verify``.

    Returns the path to a CA bundle when ``GITLAB_CA_BUNDLE`` is set, ``False``
    only when ``GITLAB_SSL_VERIFY`` explicitly says so, and ``True`` otherwise —
    including when the value is set to something unrecognised, so that a typo
    fails safe rather than failing open.
    """
    ca_bundle = os.getenv("GITLAB_CA_BUNDLE")
    if ca_bundle:
        return ca_bundle

    raw = os.getenv("GITLAB_SSL_VERIFY")
    if raw is None:
        return True

    value = raw.strip().lower()
    if value in _FALSEY:
        warnings.warn(
            "GITLAB_SSL_VERIFY is disabled: the GitLab API token will be sent over a "
            "connection whose certificate is not verified, which allows a "
            "machine-in-the-middle to read it. Prefer GITLAB_CA_BUNDLE with your "
            "internal CA certificate.",
            UserWarning,
            stacklevel=2,
        )
        return False
    if value in _TRUTHY:
        return True

    warnings.warn(
        f"GITLAB_SSL_VERIFY={raw!r} is not a recognised boolean; "
        "keeping certificate verification enabled.",
        UserWarning,
        stacklevel=2,
    )
    return True


def build_gitlab_client() -> gitlab.Gitlab:
    """Builds an authenticated GitLab client from the environment."""
    url = os.getenv("GITLAB_URL")
    token = os.getenv("GITLAB_TOKEN")

    if not url:
        raise MissingCredentialsError("GITLAB_URL is not set.")
    if not token:
        raise MissingCredentialsError("GITLAB_TOKEN is not set.")

    return gitlab.Gitlab(url, private_token=token, ssl_verify=resolve_ssl_verify())
