"""Chat model access through an OpenAI-compatible endpoint.

The client used to be constructed with no request timeout and no retry policy.
A hung vLLM endpoint therefore hung the pipeline until CI's own timeout killed
the job — with no output, and nothing to say why (finding F-59).

Both bounds are configurable from the environment, because the right values
depend on the model and the hardware behind it, and neither should require
editing a pipeline definition.
"""

import os

import httpx
from langchain_openai import ChatOpenAI

from code_reviewer.application.ports import LLMProvider
from code_reviewer.infrastructure.observability.logging import get_logger

logger = get_logger(__name__)

#: Long enough for a large-context review on modest hardware, short enough that
#: a hung endpoint surfaces well inside a normal CI job timeout.
DEFAULT_TIMEOUT_SECONDS = 120.0

#: Retries apply to timeouts and 5xx responses. A refused or malformed request
#: fails immediately: retrying a 401 wastes time and can lock an account
#: (decision D-5).
DEFAULT_MAX_RETRIES = 2

#: Low but not zero: a review benefits from some variation in phrasing, and
#: nothing downstream depends on the exact wording.
DEFAULT_TEMPERATURE = 0.3


def _positive_float(name: str, default: float) -> float:
    """Reads a positive float from the environment, warning on nonsense."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Ignoring non-numeric setting", extra={"fields": {"variable": name, "value": raw}})
        return default
    if value <= 0:
        logger.warning("Ignoring non-positive setting", extra={"fields": {"variable": name, "value": raw}})
        return default
    return value


def _non_negative_int(name: str, default: int) -> int:
    """Reads a non-negative integer; zero is meaningful (retries disabled)."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Ignoring non-numeric setting", extra={"fields": {"variable": name, "value": raw}})
        return default
    if value < 0:
        logger.warning("Ignoring negative setting", extra={"fields": {"variable": name, "value": raw}})
        return default
    return value


class VLLMProvider(LLMProvider):
    """Builds a chat model against a vLLM or other OpenAI-compatible endpoint."""

    def __init__(
        self,
        model_name: str | None = None,
        api_url: str | None = None,
        api_key: str | None = None,
    ):
        self.model_name = model_name or os.getenv("VLLM_MODEL")
        self.api_url = api_url or os.getenv("VLLM_API_URL")
        self.api_key = api_key or os.getenv("VLLM_API_KEY")

        # An explicit client avoids a pydantic/openai argument mismatch over
        # `proxies` in the pinned versions.
        self.http_client = httpx.Client()

    def get_chat_model(self) -> ChatOpenAI:
        timeout = _positive_float("LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        retries = _non_negative_int("LLM_MAX_RETRIES", DEFAULT_MAX_RETRIES)
        temperature = _positive_float("LLM_TEMPERATURE", DEFAULT_TEMPERATURE)

        logger.debug(
            "Building chat model",
            extra={
                "fields": {
                    "model": self.model_name,
                    "timeout_s": timeout,
                    "max_retries": retries,
                }
            },
        )

        # `openai_api_base`, `openai_api_key` and `request_timeout` are
        # pydantic aliases that langchain-openai accepts at runtime but does
        # not declare in its signature, and `model_name` is validated as
        # present by LLMFactory before this is reached.
        return ChatOpenAI(  # type: ignore[call-arg]
            model=self.model_name,  # type: ignore[arg-type]
            openai_api_base=self.api_url,
            openai_api_key=self.api_key,
            temperature=temperature,
            streaming=False,
            request_timeout=timeout,
            max_retries=retries,
            http_client=self.http_client,
        )


class LLMFactory:
    """Creates a provider by name."""

    @staticmethod
    def create_provider(provider_type: str = "vllm", **kwargs) -> LLMProvider:
        if provider_type.lower() == "vllm":
            return VLLMProvider(**kwargs)
        raise ValueError(f"Unknown provider type: {provider_type}")
