"""Cliente LLM con salida JSON validada. Proveedor intercambiable (gemini | mock).
El LLM NUNCA toca dinero: solo produce opiniones estructuradas que el código valida."""
import asyncio
import json
import logging

import httpx

from . import config

log = logging.getLogger("llm")
_sem = asyncio.Semaphore(3)  # respeta el rate limit del tier gratuito


async def ask_json(system: str, user: str, schema: dict, fallback: dict) -> dict:
    if config.LLM_PROVIDER == "mock" or not config.GEMINI_API_KEY:
        return dict(fallback, _provider="mock")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
            "responseSchema": schema,
        },
    }
    async with _sem:
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=45) as c:
                    r = await c.post(url, json=payload, headers={"x-goog-api-key": config.GEMINI_API_KEY})
                if r.status_code == 429:
                    await asyncio.sleep(8 * (attempt + 1))
                    continue
                r.raise_for_status()
                txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                out = json.loads(txt)
                return {**fallback, **out, "_provider": config.GEMINI_MODEL}
            except Exception as e:
                log.warning(f"LLM intento {attempt + 1}: {e}")
                await asyncio.sleep(2)
    # Si el LLM falla, el fallback es conservador (FLAT / no operar)
    return dict(fallback, _provider="fallback", _error="llm_unavailable")


REPORT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "vote": {"type": "STRING", "enum": ["LONG", "FLAT", "EXIT"]},
        "score": {"type": "NUMBER"},
        "confidence": {"type": "INTEGER"},
        "veto": {"type": "BOOLEAN"},
        "reasons": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["vote", "score", "confidence", "veto", "reasons"],
}

CASE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"case": {"type": "STRING"}, "strength": {"type": "INTEGER"}},
    "required": ["case", "strength"],
}

JUDGE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "action": {"type": "STRING", "enum": ["BUY", "NO_TRADE", "EXIT"]},
        "template": {"type": "STRING"},
        "confidence": {"type": "INTEGER"},
        "stop_loss": {"type": "NUMBER"},
        "take_profit": {"type": "NUMBER"},
        "edge": {"type": "STRING"},
        "reasoning": {"type": "STRING"},
    },
    "required": ["action", "template", "confidence", "stop_loss", "take_profit", "edge", "reasoning"],
}
