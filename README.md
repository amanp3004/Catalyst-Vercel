# Catalyst

Catalyst is Saksham's (the Entrepreneurship Club, IIM Udaipur) daily
startup newsletter — curated by **Atlas**, an AI editor built on Gemini,
following a fixed editorial manifesto (teach before reporting, curate
don't aggregate, one dominant theme per day, diversify sectors/geographies
relentlessly). It ships as a website, an installable app with saved
bookmarks, daily/weekly emails, push notifications, and an Android app on
the Play Store — all generated from one daily AI-curated edition.

## Architecture

```
GitHub Actions (Python, own schedule + secrets)
  → generate_edition.py curates the day's edition with Gemini,
    enriches it with Pexels images, commits data/{date}.json
  → send_morning_notification.py / send_evening_reminder.py — push notifications
  → send_email_digest.py — daily email
  → send_weekly_digest.py — Saturday-style weekly digest (admin-curated, manually triggered)
        ↓ (push to main)
Vercel (static site + one serverless function)
  → auto-redeploys on every push
  → serves index.html, admin.html, app.html, privacy.html, data/*.json,
    icons/, manifest*.json, sw.js, .well-known/assetlinks.json
  → api/auth-callback.js — the one serverless function, handles
    server-side Google Sign-In for mobile/PWA (see "Auth" below)
        ↕
Firebase (Auth + Firestore)
  → Auth: admin login (email/password) + end-user Google Sign-In
  → Firestore: email lists, founders roster, weekly digest curation/
    archive, per-user bookmarks, admin allowlist — see "Firestore" below
        ↕
Cloudinary (free tier)
  → founder photo uploads from admin.html (not Firebase Storage — that
    needs a paid Blaze plan; Cloudinary's free tier doesn't)
```

Vercel only ever serves static files, except for the one auth callback
function. All content generation, email, and push logic runs on GitHub
Actions on a schedule; the admin panel and end-user app talk to Firebase
directly from the browser.

## The four pages

| Page | Audience | Auth | What it does |
|---|---|---|---|
| `index.html` | Public | None | The daily edition — today's theme, Startup Brief, Startup Breakdown, Trend Cards, Builder's Lexicon, Editor's Note, Founders' Friday (Fridays only). Browse the last 8 days via the archive dropdown. |
| `app.html` | Public (bookmarks need sign-in) | Google Sign-In | Same daily content as `index.html`, plus a Bookmarks tab — heart any news item, startup, founder, or vocabulary term to save it, with a native-style bottom nav bar on mobile. **Never edit `index.html` when changing this** — they're deliberately separate files with duplicated rendering logic. |
| `admin.html` | Admins only | Email/password + Firestore allowlist | Five tabs: Email Lists, Founders' Friday, Weekly Digest, Weekly Digest History, and the founder roster. See "Admin panel" below. |
| `privacy.html` | Public | None | Privacy policy, required for the Play Store listing. |

## Daily edition generation (`generate_edition.py`)

Runs on a 2-hour cadence, 12:10 AM through 12:10 PM IST (7 scheduled
triggers) — this is a **safety net, not seven editions**: a lightweight
first step checks GitHub's API for whether `data/{today}.json` already
exists *before* even checking out the repo, and skips the entire expensive
job (checkout, Python setup, pip install, generation) if so. Content is
locked once generated for the day; if a run fails outright (a timeout, a
malformed generation after retries), the next scheduled trigger gets a
genuinely fresh attempt, since a failed run never creates that lock file.

**Sources**: a mix of direct tech/startup RSS feeds (TechCrunch, YourStory,
Inc42, Entrackr, VentureBeat, Sifted) and Google News topic searches
specifically chosen as a counterweight to the tech feeds' AI/US bias
(India business, non-AI sectors, Europe, Southeast Asia), plus Hacker News.

**Anti-repetition and anti-AI-overload** — both are enforced at the code
level, not just prompt instructions, because plain instructions were
observed to get ignored after enough consecutive days:
- Recently-used Builder's Lexicon terms and recently-featured Startup
  Breakdown companies are tracked in `data/lexicon_history.json` /
  `data/company_history.json` (independent of the pruned edition files —
  see below) and excluded; if Gemini picks one anyway, the code catches
  the collision and retries with it explicitly excluded.
- Builder's Lexicon terms are also checked against a banned-jargon pattern
  (`hallucination`, `fine-tuning`, `API`, etc.) — the term must be a real
  business/strategy/finance concept, never raw AI/ML vocabulary, even on
  an AI-themed day.
- If 3+ of the last 5 themes were AI-related, a dynamically-generated
  directive citing the actual offending themes gets injected into the
  next prompt, forcing an active search for a non-AI angle.

**Image/domain enrichment**: each brief item, trend card, and the theme
itself get a Pexels stock photo; every company domain gets verified to
actually resolve before shipping it to the frontend (Gemini occasionally
hallucinates a plausible-but-wrong domain for lesser-known companies) —
an unverified domain degrades to a clean fallback avatar rather than a
broken or misleading logo.

**Pruning**: `data/` keeps only the most recent 8 dated edition files
(`prune_old_editions`, called after every save). 8, not 7: `generate_edition.py`
runs before `send_weekly_digest.py` wants "past 7 days ending yesterday,"
so keeping one extra day guarantees that window is always still on disk.
Term/company history survives pruning independently via the two history
files above.

**Founders' Friday** (`apply_founder_spotlight`): on Fridays only, swaps
the AI-picked Startup Breakdown for a real IIM Udaipur founder's own
startup, picked from Firestore's `founders` collection (least-recently-
featured first). Every fact shown about the founder — name, company,
LinkedIn, learning — comes directly from what an admin typed or uploaded
via `admin.html`, never from Gemini, specifically to avoid any
hallucination risk about a real, named person. Gracefully does nothing
(normal edition, no crash) if the roster is empty or Firebase isn't
configured.

## Weekly Digest (`send_weekly_digest.py`)

Manually triggered only (Actions tab → "Run workflow" — no schedule).
Pulls the past 7 days of already-published news, startups (from each
day's Startup Breakdown), and Builder's Lexicon terms, then either:
- **Uses an admin's curated picks** if one exists in Firestore
  (`weekly_digest_selections/current`, set via `admin.html`'s Weekly
  Digest tab) — Gemini only writes a one-line "why it matters for
  MBA/IIM readers" framing for the already-chosen items, never selects.
- **Falls back to Gemini auto-curation** if nothing was curated that
  week — same structural safety as Founders' Friday: Gemini only ever
  returns an index into an already-real pool, never authors a new title/
  company/URL.

Email has zero clickable links anywhere in the body (a deliberate design
choice) except the mailto-based `List-Unsubscribe` header. After a
successful send, the selection gets archived (full snapshot, not just
references — survives later pruning) to `weekly_digest_archive` and
`weekly_digest_selections/current` is deleted, so the admin tab naturally
resets to nothing-checked for the next week.

`admin.html`'s Weekly Digest tab also has a **Preview / Copy / Download**
feature — a JS port of this script's `build_html()`/`build_text()`
functions, letting an admin see or manually send the email without
triggering the real automated flow (useful as a fallback, or to send via
a personal email client). Keep these two in sync if the email layout ever
changes.

## Admin panel (`admin.html`)

**Auth**: email/password sign-in, gated by a Firestore `admins`
collection — a document must exist at `admins/{exact-sign-in-email}` for
`admin.html` to actually show the panel (checked by attempting a real
admin-only Firestore read after sign-in; a permission-denied error signs
the user back out with a clear message). The `admins` collection itself
is completely locked down (`allow read, write: if false` for everyone,
including admins) — only Firebase Console can add/remove entries, since
Firestore's `exists()` rule helper can see a document regardless of that
document's own read rule. **This exists because `app.html` added Google
Sign-In to the same Firebase project — without this allowlist, anyone who
signed in there to bookmark an article would also count as "signed in"
for `admin.html`'s old, weaker `if (user)` check.**

**Tabs**:
- **Email Lists** — manage recipient lists for `send_email_digest.py`. Bulk
  upload via Excel/CSV (scans every cell of every sheet for anything that
  looks like an email — no required column layout), only ever adds new
  addresses, dedupes case-insensitively.
- **Founders' Friday** — the roster send_weekly_digest.py's `founders`
  spotlight logic picks from. Search/filter/paginated accordion list, Excel
  bulk upload (append-only, same pattern as Email Lists), Cloudinary photo
  upload per founder.
- **Weekly Digest** — curate the next weekly send: search/select from
  News, Startups, and Vocabulary pools (2-column grid), a closing
  quote + optional attribution field, and Preview/Copy/Download.
- **Weekly Digest History** — every past send, expandable to see exactly
  what went out.

## `app.html` — the bookmarking app

Duplicates `index.html`'s daily-content rendering (deliberately — the two
must never be merged, since `index.html` must stay untouched and fully
public), adding:

- **Two tabs**: Home (the daily content) and Bookmarks, with a bottom nav
  bar on mobile (`display-mode: standalone` or a narrow viewport) and top
  pill tabs on desktop, kept in sync through one shared `switchMainTab()`.
- **Hearts** on every news item, the Startup Breakdown, the Founder
  Spotlight (Fridays), and the Builder's Lexicon card. Tapping one while
  signed out shows an in-page "Want to bookmark 'X'?" prompt before
  triggering sign-in — not a bare OAuth popup with no context.
- **Bookmark storage**: one Firestore document *per bookmark*, under
  `user_bookmarks/{uid}/{type}/{hashKey}` — deliberately not one array
  field on a single document, which is a well-documented Firestore
  anti-pattern: two rapid toggles both reading the same "before" array
  and whichever write lands last silently overwriting the other's change.
  Independent documents can't collide this way, and it removes the need
  for a read-before-write entirely.
- **Optimistic UI**: the heart fills/unfills instantly on tap, before any
  network round trip; only reverted if the Firestore write actually fails.
- **Bookmarks tab**: accordion rows — collapsed shows title/name, expanded
  shows the real content (summary, "what it does," the founder's learning
  quote, or the lexicon definition) plus an outbound link where one
  genuinely exists (the source article, the startup's own domain, the
  founder's LinkedIn) — a bare title with nothing else was explicitly
  called out as useless and redesigned.

### Auth — why there are two different sign-in paths

Desktop uses a plain `signInWithPopup()` — works fine, no issues.

**Mobile/installed-PWA uses a fully server-side flow instead**
(`api/auth-callback.js`), not Firebase's own `signInWithRedirect()`. This
was tested and confirmed broken on *both* iOS and Android: sign-in
appears to complete (lands back in the app), but the resulting session
doesn't reliably persist — a known, unresolved class of bug with
Firebase Auth's client-side redirect state inside installed standalone
PWAs. The fix: the whole OAuth exchange happens in a Vercel serverless
function, and the client only ever calls `signInWithCustomToken()` — a
plain SDK call with zero cross-origin navigation involved, so there's no
client-side storage state that can get lost across a redirect.

`api/auth-callback.js` reuses the same Firebase user (`getUserByEmail`)
if one already exists for that email from an earlier desktop sign-in,
rather than creating a second, disconnected identity — otherwise a
person's desktop and mobile bookmarks would silently fragment across two
different accounts.

**Needs three Vercel environment variables** (separate from GitHub's
secrets — Vercel functions can't read GitHub Actions secrets):
`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`,
`FIREBASE_SERVICE_ACCOUNT_JSON`. The Client ID is also hardcoded into
`app.html` directly (not secret, safe to be public).

## Android app (Play Store)

Published as a **Trusted Web Activity** (a thin native wrapper showing
`app.html` full-screen via Chrome, generated through
[PWABuilder](https://pwabuilder.com) — no native Android code written).
Two things make this work:
- `manifest-app.json` — `app.html`'s own manifest (separate from
  `manifest.json`, which is `index.html`'s — installing one never affects
  the other's already-installed PWA users).
- `.well-known/assetlinks.json` — proves to Android that the TWA package
  genuinely belongs to this domain. Must stay reachable at
  `https://<domain>/.well-known/assetlinks.json`; without it Android shows
  browser UI instead of a clean native-looking app.

The Play Store signing keystore (`signing.keystore` + its password) is
**not in this repo** — it's the one irreplaceable artifact needed to ship
any future update to the same Play Store listing; back it up somewhere
durable and secure, outside of any chat or repo.

## Firestore collections

| Collection | Written by | Read by | Rule |
|---|---|---|---|
| `subscribers` | Public (push notification opt-in) | Nobody | Self-service write only, no read |
| `admins` | Firebase Console only | Nobody (used only via `exists()` inside other rules) | Fully locked |
| `email_lists` | `admin.html` | `send_email_digest.py` | Admin-only |
| `founders` | `admin.html` | `generate_edition.py`, `admin.html` | Admin-only |
| `weekly_digest_selections` | `admin.html` | `send_weekly_digest.py` | Admin-only |
| `weekly_digest_archive` | `send_weekly_digest.py` | `admin.html` | Admin-only |
| `user_bookmarks/{uid}/{type}/{doc}` | `app.html` | `app.html` | Owner-only (`request.auth.uid == uid`) |

Full current rules content is tracked in conversation history with the
project's maintainer, not duplicated here to avoid drift between two
copies — check Firebase Console directly for what's actually published.

## Required secrets

**GitHub Actions** (Settings → Secrets and variables → Actions):
`GEMINI_API_KEY`, `PEXELS_API_KEY`, `FIREBASE_SERVICE_ACCOUNT_JSON`,
`GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `SITE_URL`

**Vercel** (Project Settings → Environment Variables — a separate store,
does not share values with GitHub even for identically-named ones):
`FIREBASE_SERVICE_ACCOUNT_JSON`, `GOOGLE_OAUTH_CLIENT_ID`,
`GOOGLE_OAUTH_CLIENT_SECRET`

## Costs

Gemini (free tier), Pexels (free tier), Firebase Firestore/Auth (free
Spark plan — no Storage needed, Cloudinary covers photo uploads instead),
Cloudinary (free tier), Vercel (free tier, static site + one lightweight
serverless function), GitHub Actions (free for public repos). The Google
Play Store listing is a one-time $25 developer registration fee; an Apple
Developer account ($99/year) would only be needed if Apple Sign-In or an
iOS App Store listing is ever added later — neither exists today.
