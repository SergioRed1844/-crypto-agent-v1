from pathlib import Path

path = Path("server.py")
text = path.read_text(encoding="utf-8")

start_marker = 'async def call_gemini(prompt: str, system: str = SYSTEM_PROMPT) -> dict:'
end_marker = '\n\n# ══════════════════════════════════════════════════════════\n# RISK MANAGER'

start = text.find(start_marker)
end = text.find(end_marker)

if start == -1 or end == -1 or end <= start:
    raise SystemExit("No encontré el bloque call_gemini() en server.py")

new_block = '''async def call_gemini(prompt: str, system: str = SYSTEM_PROMPT) -> dict:
    """Call Gemini 2.5 Flash API (free tier)."""
    if not GEMINI_API_KEY:
        log.error("GEMINI_API_KEY not set")
        return {"action": "NO_TRADE", "reasoning": "API key not configured"}

    url = "https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
    }
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": system + "\\n\\n---\\n\\n" + prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "topP": 0.8,
            "maxOutputTokens": 2048
        }
    }

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]

            text = text.strip()
            if text.startswith("```"):
                text = text.split("\\n", 1)[1] if "\\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            return json.loads(text)

        except json.JSONDecodeError as e:
            log.error(f"Gemini JSON parse error: {e}. Raw text: {text[:200]}")
            return {"action": "NO_TRADE", "reasoning": "LLM returned invalid JSON"}

        except httpx.HTTPStatusError as e:
            body = e.response.text
            log.error(f"Gemini HTTP error status={e.response.status_code} body={body}")
            return {"action": "NO_TRADE", "reasoning": f"LLM error: HTTP {e.response.status_code} | {body[:300]}"}

        except Exception as e:
            log.error(f"Gemini error: {e}")
            return {"action": "NO_TRADE", "reasoning": f"LLM error: {str(e)}"}
'''

new_text = text[:start] + new_block + text[end:]
path.write_text(new_text, encoding="utf-8")

print("OK: call_gemini() reemplazado automáticamente en server.py")
