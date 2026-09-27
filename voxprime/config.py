"""
Configuration — load environment variables and app-wide settings.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Server identity
    SERVER_NAME: str = os.getenv("SERVER_NAME", "VoxPrime")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # LLM Configuration (Qwen 3.5 via Ollama)
    LLM_MODEL: str = os.getenv("LLM_MODEL", "qwen3.5:latest")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "http://localhost:11434")
    # When set, image/screenshot turns use this Ollama model (e.g. qwen2.5vl:latest)
    VISION_MODEL: str = os.getenv("VOXPRIME_VISION_MODEL", "").strip()

    # Ollama settings
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    # Tool settings
    MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "8192"))
    TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.7"))


config = Config()
