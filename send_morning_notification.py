"""
send_morning_notification.py — sends the "today's edition is live" push
notification. Runs on its own schedule (7:30 AM IST), separate from
generation (2:00 AM IST), so content is ready well before the notification
goes out.

Requires FIREBASE_SERVICE_ACCOUNT_JSON. Reads data/latest.json, which must
already exist (i.e. daily-edition.yml must have run first that day).
"""

import os
import json

from push_utils import send_push
from edition_utils import load_todays_edition

SITE_URL = os.environ.get("SITE_URL")
if not SITE_URL:
    raise SystemExit(
        "SITE_URL environment variable is not set. Refusing to send a "
        "notification with a broken placeholder link — add a 'SITE_URL' "
        "repo secret with your real live site URL."
    )


if __name__ == "__main__":
    edition = load_todays_edition()
    title = f"📌 {edition['theme']}"
    body = edition["brief"][0]["title"] if edition.get("brief") else "Today's edition is live."
    print(f"Sending morning notification: {title} — {body}")
    send_push(title=title, body=body, click_url=SITE_URL)
    print("Done.")
