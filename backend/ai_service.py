"""AI providers: Claude Sonnet 4.6 (text primary), Gemini 3 Flash (fallback), Nano Banana (images)."""
import os
import json
import base64
import logging
import re
import asyncio
from typing import Optional
from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

logger = logging.getLogger(__name__)

EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")

TEXT_PRIMARY = ("anthropic", "claude-sonnet-4-6")
TEXT_FALLBACK = ("gemini", "gemini-3-flash-preview")
IMAGE_MODEL = ("gemini", "gemini-3.1-flash-image-preview")


def _extract_json(text: str) -> dict:
    """Robust JSON extraction from LLM output."""
    text = text.strip()
    # Strip markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # Find first { and last }
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


async def _text_call(provider: str, model: str, system: str, user: str, session_id: str) -> str:
    chat = LlmChat(api_key=EMERGENT_KEY, session_id=session_id, system_message=system).with_model(provider, model)
    resp = await chat.send_message(UserMessage(text=user))
    return resp if isinstance(resp, str) else str(resp)


async def generate_json(system: str, user: str, session_id: str, retries: int = 2) -> dict:
    """Generate JSON via Claude primary, Gemini fallback."""
    last_err = None
    for provider, model in [TEXT_PRIMARY, TEXT_FALLBACK]:
        for attempt in range(retries):
            try:
                raw = await _text_call(provider, model, system, user, f"{session_id}-{provider}-{attempt}")
                return _extract_json(raw)
            except Exception as e:
                logger.warning(f"AI text call failed ({provider}, attempt {attempt}): {e}")
                last_err = e
                await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"All text providers failed: {last_err}")


async def generate_image(prompt: str, session_id: str, reference_images: Optional[list[bytes]] = None) -> bytes:
    """Generate a single image via Nano Banana. Optionally with reference images for character consistency."""
    provider, model = IMAGE_MODEL
    last_err = None
    for attempt in range(3):
        try:
            chat = LlmChat(api_key=EMERGENT_KEY, session_id=f"{session_id}-img-{attempt}",
                           system_message="You are a professional manga panel illustrator.")
            chat.with_model(provider, model).with_params(modalities=["image", "text"])

            file_contents = []
            if reference_images:
                for img_bytes in reference_images[:3]:
                    b64 = base64.b64encode(img_bytes).decode("utf-8")
                    file_contents.append(ImageContent(image_base64=b64))

            msg = UserMessage(text=prompt, file_contents=file_contents or None)
            _text, images = await chat.send_message_multimodal_response(msg)
            if not images:
                raise RuntimeError("No image returned from model")
            return base64.b64decode(images[0]["data"])
        except Exception as e:
            logger.warning(f"Image gen attempt {attempt} failed: {e}")
            last_err = e
            await asyncio.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Image generation failed after retries: {last_err}")
