"""Step 5 — assembling the identity from the things actually in use."""

from code_reviewer.domain.policy import ReviewPolicy
from code_reviewer.infrastructure.governance.identity import (
    EVALUATION_BASELINE,
    build_run_identity,
    package_version,
    prompt_fingerprint,
)


def test_the_identity_names_every_version_that_produced_the_review():
    identity = build_run_identity(ReviewPolicy(), environment={"VLLM_MODEL": "qwen3-8b"})

    assert identity.package_version == package_version()
    assert identity.policy_version == ReviewPolicy().version
    assert identity.model == "qwen3-8b"
    assert identity.prompt_fingerprint == prompt_fingerprint()
    assert identity.evaluation_baseline == EVALUATION_BASELINE


def test_a_run_with_no_model_records_none_rather_than_nothing():
    """A static-only review is a real review, and an absent field reads as an
    oversight rather than as a fact about the run."""
    identity = build_run_identity(ReviewPolicy(), environment={})

    assert identity.model == "none"


def test_a_blank_model_variable_is_the_same_as_an_unset_one():
    identity = build_run_identity(ReviewPolicy(), environment={"VLLM_MODEL": "   "})

    assert identity.model == "none"


def test_the_package_version_is_never_empty():
    """A record that cannot name the version that produced it is refused, so
    an editable checkout with no metadata must still yield something."""
    assert package_version().strip()


def test_the_fingerprint_covers_the_generalist_and_every_specialism():
    """Changing any one of the five prompts has to change the digest, or the
    fingerprint answers a question nobody asked."""
    from code_reviewer.domain.orchestration import Specialism
    from code_reviewer.domain.provenance import fingerprint
    from code_reviewer.infrastructure.llm.review_agent import ReviewAgent
    from code_reviewer.infrastructure.llm.specialist_agent import system_prompt_for

    prompts = [ReviewAgent.SYSTEM_TEMPLATE] + [
        system_prompt_for(specialism) for specialism in Specialism
    ]

    assert prompt_fingerprint() == fingerprint(*prompts)
    for index in range(len(prompts)):
        mutated = list(prompts)
        mutated[index] += " and be brief"
        assert fingerprint(*mutated) != prompt_fingerprint()
