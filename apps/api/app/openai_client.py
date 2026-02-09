import re, json
import httpx
from .settings import settings

SYSTEM_PROMPT = (
    "You are a social media copywriter. Output STRICT JSON only, no markdown. "
    "Language: English."
)

def _extract_json(text: str) -> dict:
    # Try strict JSON first
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)
    # Fallback: find first {...}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("No JSON found")
    return json.loads(m.group(0))

async def generate_english_content(original_caption: str | None, media_type: str) -> dict:
    prompt = {
        "task": "Write an English social caption based on the source caption. Keep it punchy, natural, and safe.",
        "source_caption": (original_caption or "").strip(),
        "media_type": media_type,
        "requirements": {
            "title_max_chars": 60,
            "caption_max_words": 120,
            "hashtags_count": "12-18",
            "tone": "friendly, confident, non-spammy",
            "avoid": ["clickbait", "medical/legal claims", "hate/harassment"]
        },
        "output_json_schema": {
            "title": "string",
            "caption": "string",
            "hashtags": ["#tag1", "#tag2"]
        }
    }

    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}
    payload = {
        "model": settings.OPENAI_MODEL,
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(prompt)}
        ],
        # GPT-5 family: use max_completion_tokens (not max_tokens)
        "max_completion_tokens": 700,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post("https://api.openai.com/v1/responses", headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()

    # Responses API returns a list of output items; extract text
    text = ""
    for item in data.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    text += c.get("text", "")
    if not text:
        # fallback attempt
        text = json.dumps(data)

    obj = _extract_json(text)
    title = str(obj.get("title", "")).strip()[:60]
    caption = str(obj.get("caption", "")).strip()
    hashtags = obj.get("hashtags", [])
    if isinstance(hashtags, str):
        hashtags = [h.strip() for h in hashtags.split() if h.strip().startswith("#")]
    hashtags = [h if h.startswith("#") else f"#{h}" for h in hashtags][:20]
    return {"title": title or "New post", "caption": caption or (original_caption or ""), "hashtags": hashtags or ["#socialmedia", "#content"]}
