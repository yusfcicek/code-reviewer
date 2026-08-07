from abc import ABC, abstractmethod
from typing import Any, List, Dict, Optional

class LLMProvider(ABC):
    """Factory Pattern Interface for LLM Providers."""
    
    @abstractmethod
    def get_chat_model(self) -> Any:
        """Returns a LangChain compatible ChatModel."""
        pass

class MemoryStrategy(ABC):
    """Strategy Pattern Interface for Memory Management."""
    
    @abstractmethod
    def load_context(self) -> str:
        """Returns the context string to be injected."""
        pass
    
    @abstractmethod
    def save_context(self, input_text: str, output_text: str) -> None:
        """Saves interaction to memory."""
        pass

    @abstractmethod
    def log_insight(self, insight: str) -> None:
        """Logs a persistent insight/memory."""
        pass

    @abstractmethod
    def get_memory_object(self) -> Any:
        """Returns the underlying LangChain memory object if applicable."""
        pass
