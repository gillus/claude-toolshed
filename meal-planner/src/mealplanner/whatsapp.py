"""Send WhatsApp messages via the CallMeBot personal API."""

from __future__ import annotations

import httpx

API_URL = "https://api.callmebot.com/whatsapp.php"
MAX_PART_LEN = 1500  # keep GET URLs a safe length

SETUP_HELP = (
    "CallMeBot is not configured. One-time setup: "
    "1) Add +34 644 71 81 99 to your phone contacts. "
    "2) Send it the WhatsApp message: 'I allow callmebot to send me messages'. "
    "3) You'll receive your personal API key. "
    "4) Set CALLMEBOT_PHONE (e.g. +391234567890) and CALLMEBOT_APIKEY in the "
    "MCP server's env config and restart the server."
)


def split_message(text: str, max_len: int = MAX_PART_LEN) -> list[str]:
    if len(text) <= max_len:
        return [text]
    parts: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            parts.append(remaining)
            break
        cut = remaining.rfind("\n", 0, max_len)
        if cut <= 0:
            cut = max_len
        parts.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    return parts


def send(message: str, phone: str | None, apikey: str | None) -> dict:
    if not phone or not apikey:
        return {"sent": False, "parts": 0, "detail": SETUP_HELP}

    parts = split_message(message)
    for i, part in enumerate(parts, 1):
        try:
            resp = httpx.get(
                API_URL,
                params={"phone": phone, "apikey": apikey, "text": part},
                timeout=30.0,
            )
        except httpx.HTTPError as e:
            return {
                "sent": False,
                "parts": i - 1,
                "detail": f"network error on part {i}/{len(parts)}: {type(e).__name__}",
            }
        body = resp.text[:300]
        if resp.status_code != 200 or "APIKey is invalid" in body:
            return {
                "sent": False,
                "parts": i - 1,
                "detail": f"CallMeBot error on part {i}/{len(parts)} "
                          f"(HTTP {resp.status_code}): {body}",
            }
    return {"sent": True, "parts": len(parts), "detail": "delivered to CallMeBot"}
