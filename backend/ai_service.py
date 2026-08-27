"""AI provider'ları: Metin -> Google Gemini (ücretsiz katman), Görsel -> Pollinations.ai (anahtarsız, ücretsiz)."""
import os
import json
import logging
import re
import asyncio
import hashlib
import urllib.parse
from typing import Optional

import google.generativeai as genai
import requests

logger = logging.getLogger(__name__)

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "").strip()
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

# Google Gemini modelleri (ücretsiz katmanda mevcut)
TEXT_PRIMARY = "gemini-2.0-flash-exp"
TEXT_FALLBACK = "gemini-1.5-flash"

# Pollinations.ai — API anahtarı yok, GET request, görsel byte'ları döner
POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}"


def _extract_json(text: str) -> dict:
    """LLM çıktısından JSON'ı robust şekilde çıkar."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


def _text_call_sync(model_name: str, system: str, user: str) -> str:
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY .env dosyasında ayarlı değil")
    model = genai.GenerativeModel(model_name=model_name, system_instruction=system)
    resp = model.generate_content(
        user,
        generation_config={
            "temperature": 0.9,
            "response_mime_type": "application/json",
            "max_output_tokens": 8192,
        },
    )
    if not resp.candidates or not resp.candidates[0].content.parts:
        raise RuntimeError("Boş yanıt döndü")
    return "".join(p.text for p in resp.candidates[0].content.parts if hasattr(p, "text") and p.text)


async def generate_json(system: str, user: str, session_id: str, retries: int = 2) -> dict:
    """Gemini üzerinden JSON üretimi. Primary + fallback + retry."""
    if not GOOGLE_API_KEY:
        # Retry döngüsüne girmeden hızlı başarısızlık
        raise RuntimeError("GOOGLE_API_KEY .env dosyasında ayarlı değil")
    last_err = None
    for model_name in [TEXT_PRIMARY, TEXT_FALLBACK]:
        for attempt in range(retries):
            try:
                raw = await asyncio.to_thread(_text_call_sync, model_name, system, user)
                return _extract_json(raw)
            except Exception as e:
                logger.warning(f"Gemini metin çağrısı başarısız ({model_name}, deneme {attempt}): {e}")
                last_err = e
                await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Tüm metin sağlayıcıları başarısız oldu: {last_err}")


def _fetch_pollinations_sync(prompt: str, seed: int) -> bytes:
    # Pollinations URL yolunda %0A (newline) reddediliyor; whitespace'i normalize et
    clean = " ".join(prompt.split())[:1500]
    safe_prompt = urllib.parse.quote(clean, safe="")
    url = POLLINATIONS_URL.format(prompt=safe_prompt)
    params = {
        "width": 768,
        "height": 1024,
        "seed": seed,
        "nologo": "true",
        "model": "flux",
        "enhance": "true",
    }
    resp = requests.get(url, params=params, timeout=120)
    resp.raise_for_status()
    if not resp.content or len(resp.content) < 1000:
        raise RuntimeError("Görsel çok küçük veya boş")
    return resp.content


# Pollinations aynı anda paralel çağrılırsa 429 dönüyor -> tekli semafor ile serileştir
_pollinations_lock = asyncio.Semaphore(1)


async def generate_image(prompt: str, session_id: str, reference_images: Optional[list] = None) -> bytes:
    """Pollinations.ai üzerinden tek görsel üret. Reference images desteklenmiyor (ücretsiz alternatif kısıtlaması)."""
    # Deterministik seed: process restart'a dayanıklı
    seed = int(hashlib.md5(session_id.encode("utf-8")).hexdigest()[:8], 16) % (2**31)
    backoffs = [5, 15, 30]
    last_err = None
    async with _pollinations_lock:
        for attempt in range(3):
            try:
                return await asyncio.to_thread(_fetch_pollinations_sync, prompt, seed + attempt)
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else 0
                retry_after = None
                if e.response is not None:
                    retry_after = e.response.headers.get("Retry-After")
                logger.warning(f"Pollinations HTTP {status} (deneme {attempt}); Retry-After={retry_after}")
                last_err = e
                wait = int(retry_after) if (retry_after and retry_after.isdigit()) else backoffs[attempt]
                await asyncio.sleep(wait)
            except Exception as e:
                logger.warning(f"Pollinations görsel çağrısı başarısız (deneme {attempt}): {e}")
                last_err = e
                await asyncio.sleep(backoffs[attempt])
    raise RuntimeError(f"Görsel üretimi başarısız: {last_err}")
