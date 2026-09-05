"""
send_weekly_digest.py — builds and sends the "Catalyst Weekly" email: a
curated set of the past week's news, startups, and vocabulary terms for
an IIM Udaipur / MBA student audience. Triggered manually (GitHub Actions
"Run workflow", no fixed schedule) once an admin has curated the week's
picks in admin.html's "Weekly Digest" tab — or run as-is to let Gemini
auto-curate instead.

Two ways this week's content gets chosen, in priority order:

  1. ADMIN-CURATED (preferred): if an admin picked specific news items and
     startups for this week in admin.html's "Weekly Digest" tab, that exact
     selection is used — Gemini only writes the "why it matters" framing
     for each, never touches which items are included.
  2. AUTO-CURATED (fallback): if no admin selection exists for this week,
     Gemini picks a reasonable set itself from the full pool, using the
     same structural safety as Founders' Friday and the admin-curation
     path: it only ever returns an index into an already-real, already-
     published list — it can never author a new title, url, domain, or
     company that doesn't already exist in that day's published edition.

Either way, every title/domain/company/what/why in the final email comes
verbatim from a day that already generated and already published — this
script never asks Gemini to invent a new fact, only to select from and
write brief framing around what's already real.

Requires:
  GEMINI_API_KEY                 — same as generate_edition.py
  GMAIL_ADDRESS                  — the Gmail address to send from
  GMAIL_APP_PASSWORD             — a Gmail "App Password" (not your normal
                                    password); generate at
                                    https://myaccount.google.com/apppasswords
                                    (requires 2-Step Verification)
  SITE_URL                       — same as send_email_digest.py (also used
                                    to load the Saksham logo into the email)
  FIREBASE_SERVICE_ACCOUNT_JSON  — same as used for push notifications
"""

import os
import re
import json
import time
import smtplib
import ssl
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import firebase_admin
from firebase_admin import credentials, firestore

from edition_utils import today_ist, load_edition_for_date

MODEL = os.environ.get("FOUNDEROS_MODEL", "gemini-2.5-flash")
WEEKLY_SELECTIONS_COLLECTION = "weekly_digest_selections"


def _clean_credential(value):
    """Strip whitespace, including non-breaking spaces (U+00A0) that sneak
    into GitHub secrets when an app password's display spacing gets
    copy-pasted from certain browser contexts. Same defensive cleanup as
    send_email_digest.py — kept duplicated here since these are
    independently-run scripts."""
    if value is None:
        return value
    return "".join(value.split())


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GMAIL_ADDRESS = _clean_credential(os.environ.get("GMAIL_ADDRESS"))
GMAIL_APP_PASSWORD = _clean_credential(os.environ.get("GMAIL_APP_PASSWORD"))
SITE_URL = os.environ.get("SITE_URL")

if not GEMINI_API_KEY:
    raise SystemExit("GEMINI_API_KEY environment variable is not set.")
if not SITE_URL:
    raise SystemExit(
        "SITE_URL environment variable is not set. Refusing to send an "
        "email with a broken placeholder logo link — add a 'SITE_URL' "
        "repo secret with your real live site URL."
    )
if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
    raise SystemExit(
        "GMAIL_ADDRESS and/or GMAIL_APP_PASSWORD environment variables are not set.\n"
        "Generate an App Password at https://myaccount.google.com/apppasswords "
        "(requires 2-Step Verification enabled on the Gmail account)."
    )

SAKSHAM_LOGO_URL = f"{SITE_URL.rstrip('/')}/icons/partners/saksham.png"


def _get_firestore_client():
    if not firebase_admin._apps:
        raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
        if not raw:
            raise SystemExit("FIREBASE_SERVICE_ACCOUNT_JSON environment variable is not set.")
        cred = credentials.Certificate(json.loads(raw))
        firebase_admin.initialize_app(cred)
    return firestore.client()


def get_all_recipients():
    db = _get_firestore_client()
    emails = set()
    for doc in db.collection("email_lists").stream():
        for e in doc.to_dict().get("emails", []):
            emails.add(e.strip().lower())
    return sorted(emails)


def news_key(date_str, title):
    """Stable composite key shared between admin.html (where an admin
    checks items to select them) and this script (where the same key is
    used to look up which real pool item a selection refers to). Never
    trust a key alone as content — always re-look-up the real item from
    the pool by this key rather than accepting any fields alongside it."""
    return f"{date_str}::{title}"


def startup_key(date_str, company):
    return f"{date_str}::{company}"


def lexicon_key(date_str, term):
    return f"{date_str}::{term}"


def collect_week(days=7):
    """Walk backwards `days` calendar days from yesterday, relative to
    whenever this actually runs (this is manually triggered now, not on a
    fixed schedule). Pulls every Startup Brief item, every day's Startup Breakdown (as a "startup"), and every
    day's Builder's Lexicon term out of each day's already-published
    edition. Missing days (a failed generation, a day before launch, a
    day generate_edition.py's own pruning already removed) are skipped
    silently — a partial week's worth of real content beats no digest.

    Returns (news_pool, startup_pool, lexicon_terms, start_date_str,
    end_date_str, days_found).
    """
    end_date = datetime.date.fromisoformat(today_ist()) - datetime.timedelta(days=1)
    start_date = end_date - datetime.timedelta(days=days - 1)

    news_pool = []
    startup_pool = []
    lexicon_terms = []
    days_found = 0

    for offset in range(days):
        d = end_date - datetime.timedelta(days=offset)
        edition = load_edition_for_date(d.isoformat())
        if not edition:
            continue
        days_found += 1

        for item in edition.get("brief", []):
            if not item.get("title"):
                continue
            news_pool.append({
                "key": news_key(d.isoformat(), item["title"]),
                "title": item.get("title", ""),
                "summary": item.get("summary", ""),
                "domain": item.get("domain", ""),
                "image": item.get("image", ""),
                "date": d.isoformat(),
            })

        bd = edition.get("breakdown", {})
        if bd.get("company"):
            startup_pool.append({
                "key": startup_key(d.isoformat(), bd["company"]),
                "company": bd.get("company", ""),
                "what": bd.get("what", ""),
                "why": bd.get("why", ""),
                "domain": bd.get("domain", ""),
                "date": d.isoformat(),
            })

        lex = edition.get("builder_lexicon", {})
        if lex.get("term"):
            lexicon_terms.append({
                "key": lexicon_key(d.isoformat(), lex["term"]),
                "term": lex.get("term", ""),
                "definition": lex.get("definition", ""),
                "date": d.isoformat(),
            })

    return news_pool, startup_pool, lexicon_terms, start_date.isoformat(), end_date.isoformat(), days_found


def load_admin_selection():
    """Look up the admin-curated pick from admin.html's "Weekly Digest"
    tab. Stored under a single fixed doc id ("current"), not a computed
    date — since this workflow is now only ever triggered manually (no
    cron schedule), there's no fixed day of the week to key off. An admin
    curates, then triggers the send; whatever's under "current" is what
    goes out. Returns (selected_news_keys, selected_startup_keys,
    selected_lexicon_keys, closing_quote_or_None, closing_attribution, doc_exists).

    doc_exists matters: it's what distinguishes "an admin opened the tab
    and explicitly unchecked everything" (respect that — send with zero
    of that section) from "no admin ever touched this at all" (fall back
    to full auto-curation instead of sending an empty section).
    """
    db = _get_firestore_client()
    doc = db.collection(WEEKLY_SELECTIONS_COLLECTION).document("current").get()
    if not doc.exists:
        return [], [], [], None, "", False
    data = doc.to_dict()
    return (
        data.get("selected_news", []) or [],
        data.get("selected_startups", []) or [],
        data.get("selected_lexicon", []) or [],
        data.get("closing_quote") or None,
        data.get("closing_attribution") or "",
        True,
    )


def _post_to_gemini_with_retry(url, payload, max_retries=4, initial_delay=2):
    """Same retry/backoff strategy as generate_edition.py's helper of the
    same name."""
    delay = initial_delay
    response = None
    for attempt in range(1, max_retries + 1):
        response = requests.post(url, json=payload, timeout=60)
        if response.status_code not in (429, 500, 502, 503, 504):
            break
        if attempt < max_retries:
            print(f"[warn] Gemini API returned {response.status_code} (attempt {attempt}/{max_retries}). Retrying in {delay}s...")
            time.sleep(delay)
            delay *= 2
    response.raise_for_status()
    return response


def _call_gemini_json(system_instruction, user_prompt, max_tokens=4096):
    """Shared call: posts to Gemini, strips markdown fences, parses JSON.
    Returns the parsed dict, or None on any failure — every caller must
    handle None with a non-AI fallback rather than let the whole send
    fail over a single bad generation."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "system_instruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.5,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    try:
        response = _post_to_gemini_with_retry(url, payload)
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        text = re.sub(r"^```(json)?|```$", "", text, flags=re.MULTILINE).strip()
        return json.loads(text)
    except Exception as e:
        print(f"[warn] Gemini call failed: {e}")
        return None


def resolve_selection(news_pool, startup_pool, lexicon_pool, selected_news_keys, selected_startup_keys, selected_lexicon_keys):
    """Turn a saved admin selection (lists of keys) back into the real
    pool items they refer to. Keys with no matching pool item (e.g. the
    admin selected something from a day that generate_edition.py's own
    pruning has since deleted) are silently dropped rather than crashing.
    Order follows the admin's selection order, not the pool's.
    """
    news_by_key = {item["key"]: item for item in news_pool}
    startup_by_key = {item["key"]: item for item in startup_pool}
    lexicon_by_key = {item["key"]: item for item in lexicon_pool}
    news = [news_by_key[k] for k in selected_news_keys if k in news_by_key]
    startups = [startup_by_key[k] for k in selected_startup_keys if k in startup_by_key]
    lexicon = [lexicon_by_key[k] for k in selected_lexicon_keys if k in lexicon_by_key]
    return news, startups, lexicon


def auto_curate(news_pool, startup_pool, max_news=6, max_startups=3):
    """No admin selection exists for this week — ask Gemini to pick a
    reasonable set itself. Gemini only ever returns indices into the
    already-real pools; whatever it returns is looked up against the
    pool, never taken as new content (same structural safety as
    Founders' Friday's admin-curation-only design).
    """
    news_numbered = "\n".join(f"{i}. {item['title']} — {item['summary']}" for i, item in enumerate(news_pool))
    startup_numbered = "\n".join(f"{i}. {item['company']} — {item['what']}" for i, item in enumerate(startup_pool))

    system_instruction = (
        "You are Atlas, the AI editor of Catalyst, a newsletter for Saksham "
        "— the Entrepreneurship Club at IIM Udaipur. You are assembling a "
        "weekly roundup for IIM Udaipur MBA students and alumni. You will "
        "be given two numbered lists of real, already-published items — "
        "news stories and startup profiles. You must NOT invent any new "
        "item — only reference items by their index number."
    )
    user_prompt = f"""NEWS POOL:
{news_numbered or '(none available this week)'}

STARTUP POOL:
{startup_numbered or '(none available this week)'}

Select up to {max_news} news items and up to {max_startups} startups most
relevant to IIM Udaipur MBA students and alumni (career relevance, business
models worth studying, funding trends, case-study value, entrepreneurship
lessons). Respond with ONLY valid JSON, no markdown fences:

{{"news_indices": [0, 2], "startup_indices": [1]}}"""

    parsed = _call_gemini_json(system_instruction, user_prompt)
    if not parsed:
        # Total Gemini failure — fall back to the most recent items so the
        # week's email still sends rather than not going out at all.
        return news_pool[:max_news], startup_pool[:max_startups]

    news_idx = [i for i in parsed.get("news_indices", []) if isinstance(i, int) and 0 <= i < len(news_pool)]
    startup_idx = [i for i in parsed.get("startup_indices", []) if isinstance(i, int) and 0 <= i < len(startup_pool)]
    news = [news_pool[i] for i in dict.fromkeys(news_idx)]  # dedupe, preserve order
    startups = [startup_pool[i] for i in dict.fromkeys(startup_idx)]
    return news or news_pool[:max_news], startups or startup_pool[:max_startups]


def add_framing_and_vocabulary(news, lexicon_terms):
    """One Gemini call: write a short "why it matters for MBA/IIM readers"
    line for each already-selected news item, and expand each already-
    real vocabulary term into a fuller "meaning + why it's useful + where
    it applies" explanation. Gemini never sees a chance to change the
    news item's title/domain/date or the vocabulary term's actual word —
    those are always taken from the original data, never from Gemini's
    response (see the index-based merge below).

    Falls back to the original (shorter) definitions / no framing line at
    all if the call fails, rather than blocking the whole send.
    """
    if not news and not lexicon_terms:
        return news, lexicon_terms

    news_numbered = "\n".join(f"{i}. {item['title']} — {item['summary']}" for i, item in enumerate(news))
    lexicon_numbered = "\n".join(f"{i}. {t['term']} — {t['definition']}" for i, t in enumerate(lexicon_terms))

    system_instruction = (
        "You are Atlas, the AI editor of Catalyst. You write short, "
        "punchy framing for an IIM Udaipur MBA audience. You will be "
        "given already-selected real news items and already-real "
        "vocabulary terms — you only write brief explanatory text about "
        "them, you never invent new items or change the term itself."
    )
    user_prompt = f"""NEWS ITEMS (already selected, in this order):
{news_numbered or '(none)'}

VOCABULARY TERMS (already this week's real terms, in this order):
{lexicon_numbered or '(none)'}

For each news item, write ONE sentence on why it matters specifically to
an IIM/MBA reader. For each vocabulary term, write a 2-3 sentence
expansion covering: what it means, why it's useful to know, and where it
shows up in the real world (case interviews, pitch decks, term sheets,
etc). Respond with ONLY valid JSON, no markdown fences, matching:

{{
  "news_framing": ["one sentence for item 0", "one sentence for item 1"],
  "vocabulary_expansions": ["2-3 sentences for term 0", "2-3 sentences for term 1"]
}}"""

    parsed = _call_gemini_json(system_instruction, user_prompt, max_tokens=4096)

    framed_news = []
    for i, item in enumerate(news):
        framing = ""
        if parsed and isinstance(parsed.get("news_framing"), list) and i < len(parsed["news_framing"]):
            framing = parsed["news_framing"][i]
        framed_news.append({**item, "why_it_matters": framing})

    expanded_lexicon = []
    for i, term in enumerate(lexicon_terms):
        expansion = term["definition"]  # fallback: the original short definition
        if parsed and isinstance(parsed.get("vocabulary_expansions"), list) and i < len(parsed["vocabulary_expansions"]):
            candidate = parsed["vocabulary_expansions"][i]
            if candidate:
                expansion = candidate
        expanded_lexicon.append({**term, "expansion": expansion})

    return framed_news, expanded_lexicon


def format_date_range(start_date_str, end_date_str):
    start = datetime.date.fromisoformat(start_date_str)
    end = datetime.date.fromisoformat(end_date_str)
    if start.month == end.month:
        return f"{start.strftime('%b %d')}\u2013{end.strftime('%d, %Y')}"
    return f"{start.strftime('%b %d')} \u2013 {end.strftime('%b %d, %Y')}"


def build_text(news, startups, lexicon, date_range_label, closing_quote, closing_attribution):
    lines = [f"CATALYST WEEKLY \u2014 {date_range_label}", ""]
    lines.append("THIS WEEK'S TOP STORIES")
    lines.append("-" * 40)
    for item in news:
        lines.append(item["title"])
        lines.append(item["summary"])
        if item.get("why_it_matters"):
            lines.append(f"Why it matters: {item['why_it_matters']}")
        lines.append("")

    if startups:
        lines.append("STARTUPS ON OUR RADAR")
        lines.append("-" * 40)
        for s in startups:
            lines.append(s["company"])
            lines.append(s["what"])
            lines.append("")

    if lexicon:
        lines.append("ADD THIS TO YOUR FOUNDER VOCABULARY")
        lines.append("-" * 40)
        for t in lexicon:
            lines.append(t["term"])
            lines.append(t["expansion"])
            lines.append("")

    lines.append(closing_quote)
    if closing_attribution:
        lines.append(f"\u2014 {closing_attribution}")
    lines.append("")
    lines.append("Curated by Atlas \u2014 Our AI Editor")
    lines.append(f"To stop receiving this, reply to this email or contact {GMAIL_ADDRESS}.")
    return "\n".join(lines)


def build_html(news, startups, lexicon, date_range_label, closing_quote, closing_attribution):
    news_rows = ""
    for i, item in enumerate(news):
        reverse = (i % 2 == 1)
        img_cell = f'<td width="80" valign="top"><img src="{item["image"]}" width="80" height="80" style="display:block; border-radius:6px; object-fit:cover;"></td>' if item.get("image") else ""
        text_cell = f"""<td valign="top">
          <div style="font-family:Georgia,serif; font-weight:700; font-size:15px; color:#16261F; margin-bottom:4px;">{item['title']}</div>
          <div style="font-size:13px; color:#333; line-height:1.45;">{f"<b>Why it matters:</b> {item['why_it_matters']}" if item.get('why_it_matters') else item['summary']}</div>
        </td>"""
        spacer = '<td width="14"></td>' if img_cell else ""
        # "reverse" (odd-indexed) rows put the image on the right: text
        # cell first in markup, image cell last — table cell order IS
        # left-to-right visual order, there's no CSS flip involved.
        cells = f"{text_cell}{spacer}{img_cell}" if reverse else f"{img_cell}{spacer}{text_cell}"
        border = "border-bottom:1px solid #D8D2C2;" if i < len(news) - 1 else ""
        news_rows += f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:16px; padding-bottom:16px; {border}">
          <tr>{cells}</tr>
        </table>"""

    startup_rows = ""
    for i, s in enumerate(startups):
        border = "border-bottom:1px solid #D8D2C2;" if i < len(startups) - 1 else ""
        # Real favicon via Google's favicon service when a domain exists
        # (same source index.html already uses successfully — Clearbit's
        # old Logo API shut down Dec 2025), falling back to a real
        # generated-initials image when it doesn't. Both are plain <img>
        # tags — the previous version used a flexbox <div> as a fallback
        # "icon," and flexbox doesn't render in most email clients
        # (Outlook especially just drops it), which is why it looked
        # broken in the actual sent email.
        logo_url = (
            f"https://www.google.com/s2/favicons?domain={s['domain']}&sz=128"
            if s.get("domain")
            else f"https://ui-avatars.com/api/?name={requests.utils.quote(s['company'])}&background=2C4A3B&color=F6F3EC&size=128&bold=true"
        )
        startup_rows += f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:12px; padding-bottom:12px; {border}">
          <tr>
            <td width="44" valign="top"><img src="{logo_url}" width="44" height="44" style="display:block; border-radius:6px; object-fit:cover; background:#EDEAE0;"></td>
            <td width="12"></td>
            <td valign="top">
              <div style="font-family:Georgia,serif; font-weight:700; font-size:14px; color:#16261F; margin-bottom:3px;">{s['company']}</div>
              <div style="font-size:12.5px; color:#333; line-height:1.45;">{s['what']}</div>
            </td>
          </tr>
        </table>"""

    lexicon_html = "".join(f"""
      <div style="margin-bottom:14px;">
        <div style="font-family:Georgia,serif; font-weight:700; font-size:15px; color:#16261F; margin-bottom:3px;">{t['term']}</div>
        <div style="font-size:12.5px; color:#333; line-height:1.5;">{t['expansion']}</div>
      </div>
    """ for t in lexicon)

    startups_section = f"""
  <tr><td style="padding:20px 30px 4px;">
    <div style="font-size:10.5px; text-transform:uppercase; letter-spacing:0.07em; color:#B87A1E; margin-bottom:12px;">Startups on our radar</div>
    {startup_rows}
  </td></tr>""" if startups else ""

    lexicon_section = f"""
  <tr><td style="padding:20px 30px 4px;">
    <div style="font-size:10.5px; text-transform:uppercase; letter-spacing:0.07em; color:#B87A1E; margin-bottom:12px;">Add this to your founder vocabulary</div>
    {lexicon_html}
  </td></tr>""" if lexicon else ""

    return f"""
<html>
<body style="margin:0; padding:0; background:#F6F3EC; font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F6F3EC; padding:30px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#FFFFFF; border-radius:10px; overflow:hidden;">

  <tr><td style="padding:24px 30px 14px; border-bottom:3px solid #16261F;">
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td style="font-family:Georgia,serif; font-weight:700; font-size:26px; color:#16261F;">Catalyst<span style="color:#B87A1E;">.</span></td>
        <td align="right"><img src="{SAKSHAM_LOGO_URL}" alt="Saksham" height="28" style="display:block;"></td>
      </tr>
    </table>
    <div style="font-size:10.5px; color:#6B7268; margin-top:8px; letter-spacing:0.03em;">THIS WEEK'S EDITION FOR BUILDERS &middot; {date_range_label.upper()}</div>
  </td></tr>

  <tr><td style="padding:18px 30px 4px;">
    <div style="font-size:10.5px; text-transform:uppercase; letter-spacing:0.07em; color:#B87A1E; margin-bottom:12px;">This week's top stories</div>
    {news_rows}
  </td></tr>
  {startups_section}
  {lexicon_section}

  <tr><td style="padding:20px 30px 4px; text-align:center;">
    <div style="font-family:Georgia,serif; font-weight:700; font-style:italic; font-size:16px; color:#16261F; line-height:1.5; max-width:480px; margin:0 auto;">&ldquo;{closing_quote}&rdquo;</div>
    {f'<div style="font-family:Arial,Helvetica,sans-serif; font-size:12px; color:#6B7268; margin-top:8px; letter-spacing:0.02em;">&mdash; {closing_attribution}</div>' if closing_attribution else ''}
  </td></tr>

  <tr><td style="padding:8px 30px 24px; text-align:center;">
    <div style="font-size:10.5px; color:#6B7268;">Curated by Atlas &mdash; Our AI Editor</div>
    <div style="font-size:10px; color:#9B9584; margin-top:8px;">To stop receiving this, reply to this email.</div>
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
    msg["List-Unsubscribe"] = f"<mailto:{GMAIL_ADDRESS}?subject=unsubscribe>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    server.sendmail(GMAIL_ADDRESS, [recipient], msg.as_string())


CLOSING_QUOTE_DEFAULT = "Now, go build."
CLOSING_ATTRIBUTION_DEFAULT = ""

if __name__ == "__main__":
    news_pool, startup_pool, lexicon_terms, start_date_str, end_date_str, days_found = collect_week()
    date_range_label = format_date_range(start_date_str, end_date_str)
    print(f"Collected {len(news_pool)} news item(s), {len(startup_pool)} startup(s), "
          f"{len(lexicon_terms)} vocabulary term(s) from {days_found}/7 day(s) "
          f"in range {start_date_str} to {end_date_str}.")

    if not news_pool and not startup_pool:
        print("No content found in the past week's editions — nothing to send.")
        raise SystemExit(0)

    recipients = get_all_recipients()
    if not recipients:
        print("No email recipients found across any list — nothing to send.")
        raise SystemExit(0)

    selected_news_keys, selected_startup_keys, selected_lexicon_keys, custom_closing_quote, custom_closing_attribution, doc_exists = load_admin_selection()
    if doc_exists:
        print(f"Using admin-curated selection: {len(selected_news_keys)} news key(s), "
              f"{len(selected_startup_keys)} startup key(s), {len(selected_lexicon_keys)} lexicon key(s).")
        news, startups, lexicon_terms = resolve_selection(
            news_pool, startup_pool, lexicon_terms,
            selected_news_keys, selected_startup_keys, selected_lexicon_keys,
        )
        closing_quote = custom_closing_quote or CLOSING_QUOTE_DEFAULT
        closing_attribution = custom_closing_attribution
    else:
        print("No admin selection found for this week — auto-curating with Gemini.")
        news, startups = auto_curate(news_pool, startup_pool)
        # lexicon_terms stays as everything collect_week() found — the
        # original "automatic, include everything that showed up this
        # week" behavior, unchanged for weeks nobody's curated yet.
        closing_quote = CLOSING_QUOTE_DEFAULT
        closing_attribution = CLOSING_ATTRIBUTION_DEFAULT

    print(f"Final selection: {len(news)} news item(s), {len(startups)} startup(s), {len(lexicon_terms)} vocabulary term(s).")

    news, lexicon_terms = add_framing_and_vocabulary(news, lexicon_terms)

    html_body = build_html(news, startups, lexicon_terms, date_range_label, closing_quote, closing_attribution)
    text_body = build_text(news, startups, lexicon_terms, date_range_label, closing_quote, closing_attribution)
    subject = f"Catalyst Weekly \u2014 {date_range_label}"

    print(f"Sending to {len(recipients)} recipient(s) across all lists...")
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        for i, recipient in enumerate(recipients, start=1):
            send_to_recipient(server, subject, text_body, html_body, recipient)
            print(f"Sent to {recipient} ({i}/{len(recipients)})")

    print("Done.")
