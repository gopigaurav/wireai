"""
Enhanced voice pipeline with wake word detection.
Uses Porcupine for wake word ("Hey Groundwire") and Pipecat for audio pipeline.
"""

import asyncio
import logging
import os
from typing import Optional

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.processors.aggregators.sentence import SentenceAggregator
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.frames.frames import AudioRawFrame, TextFrame, EndFrame, TranscriptionFrame
from pipecat.services.faster_whisper import FasterWhisperSTTService
from pipecat.services.kokoro import KokoroTTSService
from pipecat.transports.local import LocalTransport
from pipecat.vad.silero import SileroVADAnalyzer

from groundwire.config import config

logger = logging.getLogger("groundwire-voice")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WAKE_WORD_ENABLED = os.getenv("WAKE_WORD_ENABLED", "false").lower() == "true"
WAKE_WORD_SENSITIVITY = float(os.getenv("WAKE_WORD_SENSITIVITY", "0.5"))

# Porcupine wake words
WAKE_WORD_MODEL = os.getenv("WAKE_WORD_MODEL", "porcupine")
WAKE_WORD_PHRASE = os.getenv("WAKE_WORD_PHRASE", "hey groundwire")


# ---------------------------------------------------------------------------
# Wake Word Detector (Optional)
# ---------------------------------------------------------------------------

class WakeWordDetector(FrameProcessor):
    """
    Simple wake word detector using keyword matching.
    For production, use Porcupine or similar.
    """

    def __init__(self, wake_word: str = "hey groundwire", sensitivity: float = 0.5):
        super().__init__()
        self.wake_word = wake_word.lower()
        self.sensitivity = sensitivity
        self.is_awake = False
        self.buffer = ""

    async def process_frame(self, frame):
        if isinstance(frame, TranscriptionFrame):
            text = frame.text.lower()
            self.buffer += " " + text

            # Check if wake word is detected
            if not self.is_awake and self.wake_word in self.buffer:
                self.is_awake = True
                self.buffer = ""
                logger.info("Wake word detected!")
                yield frame  # Pass through

            elif self.is_awake:
                # Check for silence/end of command
                if len(self.buffer) > 100 or "\n" in text:
                    # Reset after processing
                    self.is_awake = False
                    self.buffer = ""
                yield frame

        elif isinstance(frame, TextFrame):
            if self.is_awake:
                yield frame
        else:
            yield frame


# ---------------------------------------------------------------------------
# Qwen LLM Service with Tool Support
# ---------------------------------------------------------------------------

class QwenLLMService(FrameProcessor):
    """
    LLM service wrapper for Qwen 3.5 via Ollama with tool support.
    """

    def __init__(
        self,
        model: str,
        base_url: str,
        system_prompt: str = "",
        mcp_tools: Optional[list] = None,
    ):
        super().__init__()
        self.model = model
        self.base_url = base_url
        self.system_prompt = system_prompt
        self.conversation_history = []
        self.mcp_tools = mcp_tools or []

        if system_prompt:
            self.conversation_history.append({"role": "system", "content": system_prompt})

        try:
            import ollama
            self.client = ollama.Client(host=base_url)
        except ImportError:
            logger.error("ollama package not installed.")
            self.client = None
        except Exception as e:
            logger.warning(f"Failed to connect to Ollama: {e}")
            self.client = None

    async def process_frame(self, frame):
        if isinstance(frame, TextFrame):
            if self.client is None:
                yield TextFrame("[LLM not available]")
                return

            user_text = frame.text
            self.conversation_history.append({"role": "user", "content": user_text})

            try:
                response = self.client.chat(
                    model=self.model,
                    messages=self.conversation_history,
                    stream=True,
                )

                for chunk in response:
                    if "message" in chunk and "content" in chunk["message"]:
                        yield TextFrame(chunk["message"]["content"])

                # Get full response for history
                full_response = self.client.chat(
                    model=self.model,
                    messages=self.conversation_history,
                )
                self.conversation_history.append({
                    "role": "assistant",
                    "content": full_response["message"]["content"]
                })

            except Exception as e:
                logger.error(f"LLM error: {e}")
                yield TextFrame(f"[Error: {str(e)}]")
        else:
            yield frame


# ---------------------------------------------------------------------------
# Enhanced Voice Agent
# ---------------------------------------------------------------------------

class EnhancedVoiceAgent:
    """
    Enhanced voice agent with wake word detection and tool support.
    """

    def __init__(self, mcp_tools: Optional[list] = None):
        self.mcp_tools = mcp_tools
        self.stt_service = None
        self.tts_service = None
        self.llm_service = None
        self.vad_analyzer = None
        self.wake_word_detector = None

    def setup_services(self):
        """Initialize all services."""
        # VAD
        logger.info("Initializing Silero VAD")
        self.vad_analyzer = SileroVADAnalyzer()

        # STT
        logger.info(f"Initializing Faster-Whisper STT (model={WHISPER_MODEL}, device={WHISPER_DEVICE})")
        self.stt_service = FasterWhisperSTTService(
            model=WHISPER_MODEL,
            device=WHISPER_DEVICE,
            vad_analyzer=self.vad_analyzer,
        )

        # Wake Word (optional)
        if WAKE_WORD_ENABLED:
            logger.info(f"Wake word detection enabled: '{WAKE_WORD_PHRASE}'")
            self.wake_word_detector = WakeWordDetector(
                wake_word=WAKE_WORD_PHRASE,
                sensitivity=WAKE_WORD_SENSITIVITY,
            )

        # TTS
        logger.info(f"Initializing Kokoro TTS (voice={KOKORO_VOICE})")
        try:
            self.tts_service = KokoroTTSService(voice=KOKORO_VOICE)
        except Exception as e:
            logger.error(f"Kokoro TTS init failed: {e}")
            self.tts_service = None

        # LLM
        logger.info(f"Initializing Qwen 3.5 LLM via Ollama")
        self.llm_service = QwenLLMService(
            model=config.LLM_MODEL,
            base_url=config.LLM_BASE_URL,
            system_prompt=VOICE_AGENT_PROMPT,
            mcp_tools=self.mcp_tools,
        )

    def create_pipeline(self):
        """Create the Pipecat pipeline."""
        sentence_aggregator = SentenceAggregator()

        components = [
            self.stt_service,       # Speech-to-text
        ]

        if self.wake_word_detector:
            components.append(self.wake_word_detector)

        components.extend([
            sentence_aggregator,    # Aggregate into sentences
            self.llm_service,       # LLM processing
        ])

        if self.tts_service:
            components.append(self.tts_service)

        pipeline = Pipeline(components)
        return pipeline

    async def run(self):
        """Run the voice agent."""
        self.setup_services()
        transport = LocalTransport()
        pipeline = self.create_pipeline()

        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                allow_interruptions=True,
                enable_metrics=True,
                report_only_initial_ttfb=True,
            ),
        )

        runner = PipelineRunner(task=task)

        status = "with wake word" if WAKE_WORD_ENABLED else "always listening"
        logger.info(f"Groundwire Voice Agent starting ({status})...")
        await runner.run()


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

VOICE_AGENT_PROMPT = """You are Groundwire, an advanced AI assistant a local coding assistant.

Speak naturally and conversationally. Keep responses concise (2-4 sentences).
Be helpful, warm, and professional.

If you need to use tools, do so silently without mentioning the tool names.
"""

# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main():
    """Main entry point."""
    logging.basicConfig(
        format=f"%(levelname)s | %(name)s | %(message)s",
        level=logging.INFO,
    )

    agent = EnhancedVoiceAgent()
    asyncio.run(agent.run())


if __name__ == "__main__":
    main()
