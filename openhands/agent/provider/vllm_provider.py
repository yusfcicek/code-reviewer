import os
from langchain_openai import ChatOpenAI
from openhands.agent.core.interfaces import LLMProvider

import httpx

class VLLMProvider(LLMProvider):
    """Concrete implementation of LLMProvider for vLLM."""
    
    def __init__(self, model_name: str = None, api_url: str = None, api_key: str = None):
        self.model_name = model_name or os.getenv("VLLM_MODEL")
        self.api_url = api_url or os.getenv("VLLM_API_URL")
        self.api_key = api_key or os.getenv("VLLM_API_KEY")
        
        # Explicit http_client to avoid pydantic/openai 'proxies' arg mismatch
        self.http_client = httpx.Client()

    def get_chat_model(self) -> ChatOpenAI:
        return ChatOpenAI(
            model=self.model_name,
            openai_api_base=self.api_url,
            openai_api_key=self.api_key,
            temperature=0.7,
            streaming=False,
            http_client=self.http_client
        )

class LLMFactory:
    """Factory to create LLM Providers."""
    
    @staticmethod
    def create_provider(provider_type: str = "vllm", **kwargs) -> LLMProvider:
        if provider_type.lower() == "vllm":
            return VLLMProvider(**kwargs)
        raise ValueError(f"Unknown provider type: {provider_type}")
