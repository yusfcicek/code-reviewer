"""The checks a deployed container answers `/readyz` from.

Level 18 shipped a lambda that always said yes, because there was nothing to
check. What a container actually needs is a forge token, a model endpoint, a
policy it can load and a workspace it can read — and a probe that says "ready"
without them routes traffic to a process that will fail on its first request.

Every reason names the *setting*. `/readyz` is unauthenticated, and a probe
that echoes configuration is a configuration endpoint (contract C-3). The test
for that asserts against the values, so a future change that starts printing
them fails there rather than in a screenshot.
"""

import os
from collections.abc import Mapping
from pathlib import Path

from code_reviewer.application.health import ReadinessProbe
from code_reviewer.domain.health import CheckResult

#: Variables without which the process cannot do its job, and what breaks.
REQUIRED_SETTINGS: Mapping[str, str] = {
    "GITLAB_TOKEN": "no merge request can be read or commented on",
    "GITLAB_URL": "the forge's address is unknown",
    "REVIEW_API_TOKEN": "the service would serve unauthenticated",
}

#: Variables the model path needs. Absent under `--no-llm`, which is a real
#: deployment: the verdict comes from the analyzers either way.
MODEL_SETTINGS: Mapping[str, str] = {
    "VLLM_BASE_URL": "the review agent has no endpoint to call",
}


def missing_settings(names: Mapping[str, str], environment: Mapping[str, str] | None = None) -> list[str]:
    """Which of ``names`` are absent or blank.

    Whitespace counts as absent: `GITLAB_TOKEN=" "` is a configuration error
    dressed as a value, and treating it as set produces a 401 an hour later.
    """
    source = environment if environment is not None else os.environ
    return [name for name in names if not (source.get(name) or "").strip()]


def required_settings_check(environment: Mapping[str, str] | None = None) -> CheckResult:
    """Everything the process cannot run without."""
    missing = missing_settings(REQUIRED_SETTINGS, environment)
    if not missing:
        return CheckResult.ok("settings")
    return CheckResult.failed(
        "settings",
        "; ".join(f"{name} is not set — {REQUIRED_SETTINGS[name]}" for name in missing),
    )


def model_settings_check(environment: Mapping[str, str] | None = None) -> CheckResult:
    """The model endpoint, unless this deployment runs without one."""
    source = environment if environment is not None else os.environ
    if (source.get("REVIEW_NO_LLM") or "").strip().lower() in ("1", "true", "yes"):
        return CheckResult.ok("model")

    missing = missing_settings(MODEL_SETTINGS, environment)
    if not missing:
        return CheckResult.ok("model")
    return CheckResult.failed(
        "model", "; ".join(f"{name} is not set — {MODEL_SETTINGS[name]}" for name in missing)
    )


def workspace_check(environment: Mapping[str, str] | None = None) -> CheckResult:
    """The tree the agent is confined to, and whether it is there."""
    source = environment if environment is not None else os.environ
    root = Path((source.get("CI_PROJECT_DIR") or ".").strip() or ".")

    if not root.is_dir():
        return CheckResult.failed("workspace", "the configured workspace root is not a directory")
    return CheckResult.ok("workspace")


def policy_check(environment: Mapping[str, str] | None = None) -> CheckResult:
    """Whether the policy this deployment names can be loaded.

    Loaded rather than merely located: a policy file with an unrecognised key
    refuses to load (Level 9), and that refusal at start-up is worth far more
    than the same refusal on the first merge request.
    """
    from code_reviewer.errors import ConfigurationError
    from code_reviewer.infrastructure.config.loader import load_policy

    source = environment if environment is not None else os.environ
    path = (source.get("REVIEW_POLICY_PATH") or "").strip() or None

    try:
        load_policy(path)
    except ConfigurationError as error:
        return CheckResult.failed("policy", f"the policy could not be loaded: {error}")
    return CheckResult.ok("policy")


def build_readiness_probe(environment: Mapping[str, str] | None = None) -> ReadinessProbe:
    """The probe `/readyz` answers from."""
    return ReadinessProbe(
        {
            "settings": lambda: required_settings_check(environment),
            "model": lambda: model_settings_check(environment),
            "policy": lambda: policy_check(environment),
            "workspace": lambda: workspace_check(environment),
        }
    )
