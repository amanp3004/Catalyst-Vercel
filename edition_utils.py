"""
edition_utils.py — shared helpers for every script that consumes today's
generated edition (send_email_digest.py, send_morning_notification.py,
send_evening_reminder.py).

The one thing all three scripts need in common: don't send anything unless
today's edition actually exists and was actually generated today. Without
this check, if generate_edition.py ever fails outright (as opposed to
deliberately skipping via the same-day lock), data/latest.json would still
hold yesterday's (or older) content, and every downstream script would
silently re-send stale content as if it were new.
"""

import json
import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def today_ist():
    """Today's date in IST, as 'YYYY-MM-DD'. Matches the same helper in
    generate_edition.py — kept as a separate copy here since these are
    independently-run scripts, but must stay logically identical."""
    return datetime.datetime.now(IST).date().isoformat()


def load_todays_edition(path="data/latest.json"):
    """Load today's edition — but only if it's actually dated today (IST).

    Raises SystemExit (causing the GitHub Actions step to fail loudly, the
    same way a missing API key does elsewhere in this codebase) if:
      - the file doesn't exist at all, or
      - the file exists but its "date" field isn't today, which means
        generate_edition.py either hasn't run yet today or failed before
        it could save a fresh edition.

    Failing loudly here is deliberate: a silent no-op could hide a broken
    daily-edition.yml run for days. A red X in the Actions tab is the
    signal that something upstream needs attention.
    """
    try:
        with open(path) as f:
            edition = json.load(f)
    except FileNotFoundError:
        raise SystemExit(
            f"Refusing to send: {path} doesn't exist. This means "
            "today's edition has never been generated (daily-edition.yml "
            "hasn't run successfully yet) — nothing will be sent."
        )

    today = today_ist()
    edition_date = edition.get("date")

    if edition_date != today:
        raise SystemExit(
            f"Refusing to send: {path} is dated '{edition_date}', but "
            f"today (IST) is '{today}'. This means today's edition "
            "generation (daily-edition.yml) hasn't completed successfully "
            "yet — nothing will be sent until it has."
        )

    return edition
