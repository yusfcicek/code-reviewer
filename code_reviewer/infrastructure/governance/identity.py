"""Which version of everything produced this review.

Enough that two reviews which disagree can be attributed to the change between
them rather than to the weather (capability C-20).

The prompts are recorded as a fingerprint. Their text would put the system's
instructions into a file read more widely than the repository, for no gain;
recording nothing would make "the prompt changed" unprovable (decision D-3).
"""

import os
from collections.abc import Mapping
from importlib import metadata

from code_reviewer.domain.orchestration import Specialism
from code_reviewer.domain.policy import ReviewPolicy
from code_reviewer.domain.provenance import RunIdentity, fingerprint

#: What the analyzers last scored against the shipped dataset, and the floors
#: the CI gate holds them to. A verdict is worth more when the thing that
#: produced it has a measured accuracy.
#:
#: Kept in step with `tests/unit/test_evaluation_baseline.py` by a test there:
#: two numbers in two files drift, and this pair is exactly the pair somebody
#: would forget.
EVALUATION_BASELINE = "precision >= 0.80, recall >= 0.80, f1 >= 0.80 (lower bound) over 17 cases"


def package_version() -> str:
    """The installed version, or a stated fallback.

    A record that cannot name the version that produced it is refused, so this
    never returns an empty string — an editable checkout with no metadata is
    still a real run and worth recording as one.
    """
    try:
        return metadata.version("enterprise-ai-code-reviewer")
    except metadata.PackageNotFoundError:  # pragma: no cover - only outside an install
        return "unknown"


def prompt_fingerprint() -> str:
    """A digest of the system prompts actually in use.

    The generalist's template plus each specialism's, in composition order, so
    a change to any one of them changes the fingerprint.
    """
    from code_reviewer.infrastructure.llm.review_agent import ReviewAgent
    from code_reviewer.infrastructure.llm.specialist_agent import system_prompt_for

    return fingerprint(
        ReviewAgent.SYSTEM_TEMPLATE, *(system_prompt_for(specialism) for specialism in Specialism)
    )


def build_run_identity(policy: ReviewPolicy, environment: Mapping[str, str] | None = None) -> RunIdentity:
    """Everything that identifies this run."""
    source = environment if environment is not None else os.environ
    model = (source.get("VLLM_MODEL") or "").strip()

    return RunIdentity(
        package_version=package_version(),
        policy_version=policy.version,
        model=model or "none",
        prompt_fingerprint=prompt_fingerprint(),
        # The analyzers ship with the package, so their rule set is its
        # version. Stated rather than assumed: if the rules ever move to a
        # file of their own, this is the line that has to change.
        ruleset_version=package_version(),
        evaluation_baseline=EVALUATION_BASELINE,
    )
