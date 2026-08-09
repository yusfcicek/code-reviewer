"""Step 3 — what a running container needs, and whether it has it."""

from code_reviewer.infrastructure.deployment.settings import (
    build_readiness_probe,
    model_settings_check,
    policy_check,
    required_settings_check,
    workspace_check,
)

CONFIGURED = {
    "GITLAB_TOKEN": "glpat-AAAABBBBCCCCDDDD",
    "GITLAB_URL": "https://gitlab.example.com",
    "REVIEW_API_TOKEN": "api-token-EEEEFFFF",
    "VLLM_BASE_URL": "http://model.internal:8000/v1",
}


# -- required settings -------------------------------------------------------


def test_nothing_configured_names_every_missing_variable():
    """A probe that names one at a time costs a deploy per variable."""
    result = required_settings_check({})

    assert not result.passed
    assert "GITLAB_TOKEN" in result.reason
    assert "GITLAB_URL" in result.reason
    assert "REVIEW_API_TOKEN" in result.reason


def test_everything_configured_passes():
    assert required_settings_check(CONFIGURED).passed


def test_a_reason_says_what_breaks_without_the_variable():
    result = required_settings_check({})

    assert "no merge request can be read" in result.reason


def test_whitespace_counts_as_missing():
    """`GITLAB_TOKEN=" "` is a configuration error dressed as a value, and
    treating it as set produces a 401 an hour later."""
    result = required_settings_check({**CONFIGURED, "GITLAB_TOKEN": "   "})

    assert not result.passed
    assert "GITLAB_TOKEN" in result.reason


# -- the model ---------------------------------------------------------------


def test_a_missing_model_endpoint_fails():
    result = model_settings_check({})

    assert not result.passed
    assert "VLLM_BASE_URL" in result.reason


def test_a_deployment_without_a_model_is_still_ready():
    """The verdict comes from the analyzers either way, so running without a
    model is a real deployment rather than a broken one."""
    assert model_settings_check({"REVIEW_NO_LLM": "true"}).passed


def test_the_no_llm_flag_is_read_generously():
    for value in ("1", "true", "TRUE", "yes"):
        assert model_settings_check({"REVIEW_NO_LLM": value}).passed, value


def test_an_unrecognised_no_llm_value_does_not_disable_the_check():
    """`REVIEW_NO_LLM=maybe` is a typo, and reading it as 'yes' would silence
    a check somebody wanted."""
    assert not model_settings_check({"REVIEW_NO_LLM": "maybe"}).passed


# -- the workspace and the policy -------------------------------------------


def test_a_workspace_that_is_not_there_fails(tmp_path):
    result = workspace_check({"CI_PROJECT_DIR": str(tmp_path / "nowhere")})

    assert not result.passed
    assert "workspace root" in result.reason


def test_a_workspace_that_is_there_passes(tmp_path):
    assert workspace_check({"CI_PROJECT_DIR": str(tmp_path)}).passed


def test_the_default_workspace_is_the_working_directory():
    assert workspace_check({}).passed


def test_the_shipped_policy_loads():
    assert policy_check({}).passed


def test_a_policy_that_cannot_be_loaded_fails(tmp_path):
    broken = tmp_path / "policy.yaml"
    broken.write_text("gate:\n  nonsense_key: 1\n", encoding="utf-8")

    result = policy_check({"REVIEW_POLICY_PATH": str(broken)})

    assert not result.passed
    assert "policy could not be loaded" in result.reason


# -- the whole probe ---------------------------------------------------------


def test_a_fully_configured_probe_is_ready():
    assert build_readiness_probe(CONFIGURED).run().is_ready


def test_an_unconfigured_probe_names_several_checks():
    readiness = build_readiness_probe({}).run()

    assert not readiness.is_ready
    assert {result.name for result in readiness.failures} >= {"settings", "model"}


def test_no_configured_value_ever_appears_in_a_reason():
    """`/readyz` is unauthenticated. Asserted against the values, so a future
    change that starts echoing them fails here rather than in a screenshot."""
    readiness = build_readiness_probe({**CONFIGURED, "GITLAB_URL": ""}).run()

    text = readiness.summary() + repr(readiness)
    for value in CONFIGURED.values():
        assert value not in text, value


def test_the_probe_registers_every_check_it_documents():
    assert set(build_readiness_probe({}).check_names) == {"settings", "model", "policy", "workspace"}
