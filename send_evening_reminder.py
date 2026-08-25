"""
send_evening_reminder.py — sends a second, differently-angled push
notification later in the day, teasing a story from today's edition that
readers may have missed that morning. Run by a separate scheduled workflow.

Requires GEMINI_API_KEY and FIREBASE_SERVICE_ACCOUNT_JSON.
"""

import os
import re
import json
import requests

from push_utils import send_push
from edition_utils import load_todays_edition

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL = os.environ.get("FOUNDEROS_MODEL", "gemini-2.5-flash")
SITE_URL = os.environ.get("SITE_URL")
if not SITE_URL:
    raise SystemExit(
        "SITE_URL environment variable is not set. Refusing to send a "
        "notification with a broken placeholder link — add a 'SITE_URL' "
        "repo secret with your real live site URL."
    )

if not GEMINI_API_KEY:
    raise SystemExit("GEMINI_API_KEY environment variable is not set.")


def write_teaser(edition):
    """Ask Gemini to write a short, scroll-stopping push notification —
    Zomato-style playful urgency, not a dry headline restatement."""

    context = json.dumps({
        "theme": edition.get("theme"),
        "brief": [{"title": b["title"], "summary": b["summary"]} for b in edition.get("brief", [])],
        "breakdown_company": edition.get("breakdown", {}).get("company"),
        "breakdown_lesson": edition.get("breakdown", {}).get("lesson"),
    }, indent=2)

    prompt = f"""You write push notifications for Catalyst, a daily startup
newsletter for founders. Your job right now: write ONE evening reminder
notification that nudges someone who hasn't opened today's edition yet to
open it.

Style: playful, punchy, a little cheeky — like Zomato/Swiggy notification
copy, but for founders/business news instead of food. Create curiosity,
don't give away the full story. Use at most one emoji. No corporate tone,
no "Don't miss out on our newsletter" cliches.

Today's edition content (for context, do not just restate it):
{context}

Respond with ONLY valid JSON, no markdown fences:
{{"title": "string, max 40 characters, hooky", "body": "string, max 90 characters, creates curiosity"}}
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={GEMINI_API_KEY}"
    response = requests.post(
        url,
        json={
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.9,
                "maxOutputTokens": 1024,
                "responseMimeType": "application/json",
                # gemini-2.5-flash has extended "thinking" enabled by
                # default, which consumes tokens from the same budget as
                # the visible output. For a one-sentence JSON reply this
                # reasoning is unnecessary, and with a small token ceiling
                # it can silently eat the whole budget, leaving the
                # response with no "parts" at all. Disabling it avoids
                # that failure mode.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    try:
        candidate = data["candidates"][0]
        text = candidate["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError) as e:
        print("---- RAW GEMINI RESPONSE (missing expected fields) ----")
        print(json.dumps(data, indent=2))
        print("---- END RAW RESPONSE ----")
        finish_reason = data.get("candidates", [{}])[0].get("finishReason", "unknown")
        raise SystemExit(
            f"Gemini response was missing expected fields ({e}). "
            f"finishReason was '{finish_reason}' — if this is 'MAX_TOKENS', "
            "raise maxOutputTokens further; if 'SAFETY' or 'RECITATION', "
            "the prompt or source content triggered a content filter."
        )

    text = re.sub(r"^```(json)?|```$", "", text, flags=re.MULTILINE).strip()
    return json.loads(text)


if __name__ == "__main__":
    edition = load_todays_edition()
    print("Writing evening teaser with Gemini...")
    teaser = write_teaser(edition)
    print(f"Teaser: {teaser}")
    send_push(title=teaser["title"], body=teaser["body"], click_url=SITE_URL)
    print("Done.")
