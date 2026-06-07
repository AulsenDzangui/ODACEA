from abc import ABC, abstractmethod


class LLMProvider(ABC):

    @abstractmethod
    def complete(self, system_prompt: str, user_message: str) -> str:
        pass

    @abstractmethod
    def stream(self, system_prompt: str, user_message: str):
        pass

    def stream_with_reasoning(self, system_prompt: str, user_message: str):
        """Yields (is_thinking: bool, chunk: str). Default: no reasoning extraction."""
        for chunk in self.stream(system_prompt, user_message):
            yield False, chunk

    @abstractmethod
    def validate_connection(self) -> bool:
        pass
