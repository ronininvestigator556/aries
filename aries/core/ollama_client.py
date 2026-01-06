"""
Ollama API client for LLM communication.
"""

import asyncio
from typing import Any, AsyncIterator

import ollama
from ollama import AsyncClient

from aries.config import OllamaConfig
from aries.exceptions import OllamaConnectionError, OllamaError, OllamaModelError


class OllamaClient:
    """Async client for Ollama API."""
    
    def __init__(self, config: OllamaConfig) -> None:
        """Initialize Ollama client.
        
        Args:
            config: Ollama configuration.
        """
        self.config = config
        self.client = AsyncClient(host=config.host)
    
    async def is_available(self) -> bool:
        """Check if Ollama server is available.
        
        Returns:
            True if server is reachable.
        """
        try:
            await self.list_models()
            return True
        except Exception:
            return False
    
    async def list_models(self) -> list[dict[str, Any]]:
        """List available models.
        
        Returns:
            List of model information dictionaries.
            
        Raises:
            OllamaConnectionError: If cannot connect to server.
        """
        try:
            response = await self.client.list()
            # Handle object response (new ollama lib) or dict response (old)
            if hasattr(response, "models"):
                models = response.models
            else:
                models = response.get("models", [])
            
            # Convert to dicts if they are objects
            result = []
            for m in models:
                if hasattr(m, "model"):
                    # Object with .model attribute
                    model_dict = {
                        "name": m.model,
                        "modified_at": getattr(m, "modified_at", None),
                        "size": getattr(m, "size", 0),
                        "digest": getattr(m, "digest", ""),
                        "details": getattr(m, "details", {}),
                    }
                    result.append(model_dict)
                elif isinstance(m, dict):
                    # Already a dict, ensure 'name' key exists (map 'model' to 'name' if needed)
                    if "model" in m and "name" not in m:
                        m["name"] = m["model"]
                    result.append(m)
            return result
        except Exception as e:
            raise OllamaConnectionError(f"Failed to list models: {e}") from e
    
    async def get_model_names(self) -> list[str]:
        """Get list of model names.
        
        Returns:
            List of model name strings.
        """
        models = await self.list_models()
        return [m["name"] for m in models]
    
    async def model_exists(self, model_name: str) -> bool:
        """Check if a model exists locally.
        
        Args:
            model_name: Name of the model.
            
        Returns:
            True if model exists.
        """
        models = await self.get_model_names()
        # Handle both full names (llama3.2:latest) and short names (llama3.2)
        return any(
            model_name == m or model_name == m.split(":")[0]
            for m in models
        )

    
    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        raw: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Send chat message and get full response.

        Args:
            model: Model name to use.
            messages: List of message dictionaries.
            tools: Optional list of tools to provide to the model.
            raw: Return the full Ollama response if True.
            **kwargs: Additional parameters for Ollama.

        Returns:
            Complete response text or raw response.
            
        Raises:
            OllamaModelError: If model doesn't exist.
            OllamaError: If chat fails.
        """
        try:
            response = await self.client.chat(
                model=model,
                messages=messages,
                tools=tools,
                **kwargs,
            )
            if raw:
                if hasattr(response, "model_dump"):
                    return response.model_dump()
                return response
            
            if hasattr(response, "message"):
                return response.message.content
            return response["message"]["content"]
        except ollama.ResponseError as e:
            if "not found" in str(e).lower():
                raise OllamaModelError(f"Model not found: {model}") from e
            raise OllamaError(f"Chat failed: {e}") from e
        except Exception as e:
            raise OllamaError(f"Chat failed: {e}") from e
    
    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream chat response.
        
        Args:
            model: Model name to use.
            messages: List of message dictionaries.
            **kwargs: Additional parameters for Ollama.
            
        Yields:
            Response text chunks.
            
        Raises:
            OllamaModelError: If model doesn't exist.
            OllamaError: If chat fails.
        """
        try:
            stream = await self.client.chat(
                model=model,
                messages=messages,
                stream=True,
                **kwargs,
            )
            async for chunk in stream:
                if "message" in chunk and "content" in chunk["message"]:
                    yield chunk["message"]["content"]
        except ollama.ResponseError as e:
            if "not found" in str(e).lower():
                raise OllamaModelError(f"Model not found: {model}") from e
            raise OllamaError(f"Stream failed: {e}") from e
        except Exception as e:
            raise OllamaError(f"Stream failed: {e}") from e
    
    async def generate_embedding(
        self,
        text: str,
        model: str | None = None,
    ) -> list[float]:
        """Generate embedding for text.
        
        Args:
            text: Text to embed.
            model: Embedding model (uses config default if not specified).
            
        Returns:
            Embedding vector as list of floats.
            
        Raises:
            OllamaError: If embedding generation fails.
        """
        model = model or self.config.embedding_model
        try:
            response = await self.client.embeddings(
                model=model,
                prompt=text,
            )
            return response["embedding"]
        except Exception as e:
            raise OllamaError(f"Embedding failed: {e}") from e
    
    async def pull_model(self, model_name: str) -> AsyncIterator[dict[str, Any]]:
        """Pull a model from Ollama registry.
        
        Args:
            model_name: Name of model to pull.
            
        Yields:
            Progress updates as dictionaries.
        """
        try:
            stream = await self.client.pull(model_name, stream=True)
            async for progress in stream:
                yield progress
        except Exception as e:
            raise OllamaError(f"Failed to pull model: {e}") from e
