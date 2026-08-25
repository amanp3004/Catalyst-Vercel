"""
send_email_digest.py — builds an HTML email from today's edition and sends
it via Gmail SMTP to every email address across all lists stored in
Firestore (email_lists collection, managed via admin.html).

Requires:
  GMAIL_ADDRESS          — the Gmail address to send from
  GMAIL_APP_PASSWORD     — a Gmail "App Password" (not your normal password)
                            Generate at: https://myaccount.google.com/apppasswords
                            (requires 2-Step Verification enabled on the account)
  FIREBASE_SERVICE_ACCOUNT_JSON — same as used for push notifications
"""

import os
import json
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import firebase_admin
from firebase_admin import credentials, firestore

from edition_utils import load_todays_edition

def _clean_credential(value):
    """Strip whitespace, including non-breaking spaces (U+00A0), which sneak
    into GitHub secrets when an app password's display spacing ("abcd efgh
    ijkl mnop") gets copy-pasted from certain browser contexts. Those spaces
    are purely for display anyway — Google doesn't need them in the actual
    credential — but a stray \\xa0 crashes smtplib's ASCII-based auth step
    before it even reaches Gmail, so we strip all whitespace defensively.
    """
    if value is None:
        return value
    return "".join(value.split())


GMAIL_ADDRESS = _clean_credential(os.environ.get("GMAIL_ADDRESS"))
GMAIL_APP_PASSWORD = _clean_credential(os.environ.get("GMAIL_APP_PASSWORD"))
SITE_URL = os.environ.get("SITE_URL")
if not SITE_URL:
    raise SystemExit(
        "SITE_URL environment variable is not set. Refusing to send an "
        "email with a broken placeholder link — add a 'SITE_URL' repo "
        "secret with your real live site URL."
    )

if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
    raise SystemExit(
        "GMAIL_ADDRESS and/or GMAIL_APP_PASSWORD environment variables are not set.\n"
        "Generate an App Password at https://myaccount.google.com/apppasswords "
        "(requires 2-Step Verification enabled on the Gmail account)."
    )


def get_all_recipients():
    if not firebase_admin._apps:
        raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
        if not raw:
            raise SystemExit("FIREBASE_SERVICE_ACCOUNT_JSON environment variable is not set.")
        cred = credentials.Certificate(json.loads(raw))
        firebase_admin.initialize_app(cred)

    db = firestore.client()
    emails = set()
    for doc in db.collection("email_lists").stream():
        for e in doc.to_dict().get("emails", []):
            emails.add(e.strip().lower())
    return sorted(emails)


def build_text(edition):
    """Plain-text alternative to the HTML email. Emails with an HTML part
    but no text/plain part are a well-known spam-filter red flag — nearly
    all legitimate mail includes both."""
    theme = edition.get("theme", "")
    brief = edition.get("brief", [])
    bd = edition.get("breakdown", {})
    trend_cards = edition.get("trend_cards", [])
    note = edition.get("editors_note", {}).get("paragraphs", [])

    lines = [f"CATALYST — {theme}", "Daily Edition for Builders", ""]

    lines.append("STARTUP BRIEF")
    lines.append("-" * 40)
    for item in brief:
        lines.append(item.get("title", ""))
        lines.append(item.get("summary", ""))
        lines.append(item.get("url", ""))
        lines.append("")

    lines.append(f"STARTUP BREAKDOWN — {bd.get('company', '')}")
    lines.append("-" * 40)
    lines.append(f"What it does: {bd.get('what', '')}")
    lines.append(f"Why it matters: {bd.get('why', '')}")
    lines.append(f"Lesson: \"{bd.get('lesson', '')}\"")
    lines.append("")

    lines.append("TREND TO WATCH")
    lines.append("-" * 40)
    for card in trend_cards:
        lines.append(f"• {card.get('headline', '')}")
        lines.append(f"  {card.get('insight', '')}")
        lines.append("")

    lines.append("EDITOR'S NOTE")
    lines.append("-" * 40)
    lines.extend(note)
    lines.append("")

    lines.append(f"Read today's full edition: {SITE_URL}")
    lines.append("")
    lines.append("Curated by Atlas — Our AI Editor")
    lines.append(
        f"To stop receiving this, reply to this email or contact {GMAIL_ADDRESS}."
    )
    return "\n".join(lines)


def build_html(edition):
    theme = edition.get("theme", "")
    brief = edition.get("brief", [])
    bd = edition.get("breakdown", {})
    trend_cards = edition.get("trend_cards", [])
    note = edition.get("editors_note", {}).get("paragraphs", [])

    brief_html = "".join(f"""
      <tr><td style="padding:14px 0; border-bottom:1px solid #D8D2C2;">
        <div style="font-family:Georgia,serif; font-weight:700; font-size:17px; color:#16261F; margin-bottom:6px;">{item['title']}</div>
        <div style="font-size:14px; color:#333; line-height:1.5; margin-bottom:8px;">{item['summary']}</div>
        <a href="{item['url']}" style="font-size:12px; color:#2C4A3B; text-decoration:underline;">Read more →</a>
      </td></tr>
    """ for item in brief)

    trend_html = "".join(f"""
      <tr><td style="padding:0 0 16px;">
        {f'<img src="{card["image"]}" alt="{card.get("headline","")}" width="100%" style="display:block; width:100%; max-height:160px; object-fit:cover; border-radius:6px; margin-bottom:8px;">' if card.get('image') else ''}
        <div style="font-family:Georgia,serif; font-weight:700; font-size:15px; color:#16261F; margin-bottom:4px;">{card.get('headline','')}</div>
        <div style="font-size:13.5px; color:#333; line-height:1.55;">{card.get('insight','')}</div>
      </td></tr>
    """ for card in trend_cards)

    note_html = "".join(f'<p style="font-size:14px; color:#F6F3EC; line-height:1.6; margin-bottom:12px;">{p}</p>' for p in note)

    return f"""
<html>
<body style="margin:0; padding:0; background:#F6F3EC; font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F6F3EC; padding:30px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#FFFFFF; border-radius:10px; overflow:hidden;">

  <tr><td style="padding:28px 30px 16px; border-bottom:3px solid #16261F;">
    <span style="font-family:Georgia,serif; font-weight:700; font-size:30px; color:#16261F;">Catalyst<span style="color:#B87A1E;">.</span></span>
    <div style="font-size:11px; color:#6B7268; margin-top:6px; letter-spacing:0.03em;">DAILY EDITION FOR BUILDERS</div>
    <div style="font-size:12px; color:#6B7268; margin-top:8px;">Presented by Saksham &mdash; Entrepreneurship Club, IIM Udaipur &middot; Curated by Atlas, AI Editor</div>
  </td></tr>

  <tr><td style="padding:20px 30px; background:#2C4A3B;">
    <span style="display:inline-block; background:#16261F; color:#F6F3EC; font-size:10px; text-transform:uppercase; letter-spacing:0.06em; padding:4px 8px; border-radius:3px; margin-bottom:8px;">Today's Theme</span>
    <div style="font-family:Georgia,serif; font-weight:700; font-size:19px; color:#FFFFFF; margin-top:8px;">{theme}</div>
  </td></tr>

  <tr><td style="padding:20px 30px;">
    <div style="font-size:11px; text-transform:uppercase; letter-spacing:0.08em; color:#B87A1E; margin-bottom:6px;">Startup Brief</div>
    <table width="100%" cellpadding="0" cellspacing="0">{brief_html}</table>
  </td></tr>

  <tr><td style="padding:0 30px 20px;">
    <div style="font-size:11px; text-transform:uppercase; letter-spacing:0.08em; color:#B87A1E; margin-bottom:10px;">Startup Breakdown — {bd.get('company','')}</div>
    <div style="font-size:14px; color:#333; margin-bottom:8px;"><b>What it does:</b> {bd.get('what','')}</div>
    <div style="font-size:14px; color:#333; margin-bottom:8px;"><b>Why it matters:</b> {bd.get('why','')}</div>
    <div style="background:#FBF3E2; border-left:3px solid #E0A339; padding:10px 14px; font-style:italic; font-size:14px; color:#333;">"{bd.get('lesson','')}"</div>
  </td></tr>

  <tr><td style="padding:0 30px 20px;">
    <div style="font-size:11px; text-transform:uppercase; letter-spacing:0.08em; color:#B87A1E; margin-bottom:10px;">Trend to Watch</div>
    <table width="100%" cellpadding="0" cellspacing="0">{trend_html}</table>
  </td></tr>

  <tr><td style="padding:24px 30px; background:#2C4A3B;">
    <div style="font-size:11px; text-transform:uppercase; letter-spacing:0.08em; color:#E0A339; margin-bottom:10px;">Editor's Note</div>
    {note_html}
  </td></tr>

  <tr><td style="padding:20px 30px; text-align:center;">
    <a href="{SITE_URL}" style="display:inline-block; background:#16261F; color:#F6F3EC; text-decoration:none; padding:10px 24px; border-radius:20px; font-size:13px;">Read today's full edition →</a>
    <div style="font-size:11px; color:#6B7268; margin-top:20px;">Curated by Atlas — Our AI Editor</div>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>
"""


def send_to_recipient(server, subject, text_body, html_body, recipient):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Catalyst <{GMAIL_ADDRESS}>"
    msg["To"] = recipient
    # RFC 8058 one-click unsubscribe header. Gmail's own bulk-sender
    # guidelines expect this, and its presence (or absence) meaningfully
    # affects spam scoring for anything sent to more than a couple of
    # addresses on a recurring schedule.
    msg["List-Unsubscribe"] = f"<mailto:{GMAIL_ADDRESS}?subject=unsubscribe>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    # Order matters in multipart/alternative: plain text first, richest
    # version (html) last — clients render the last part they understand.
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    server.sendmail(GMAIL_ADDRESS, [recipient], msg.as_string())


if __name__ == "__main__":
    edition = load_todays_edition()
    recipients = get_all_recipients()

    if not recipients:
        print("No email recipients found across any list — nothing to send.")
        raise SystemExit(0)

    print(f"Sending to {len(recipients)} recipient(s) across all lists...")
    html_body = build_html(edition)
    text_body = build_text(edition)
    subject = f"Catalyst — {edition.get('theme', 'Today’s Edition')}"

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        for i, recipient in enumerate(recipients, start=1):
            send_to_recipient(server, subject, text_body, html_body, recipient)
            print(f"Sent to {recipient} ({i}/{len(recipients)})")

    print("Done.")
