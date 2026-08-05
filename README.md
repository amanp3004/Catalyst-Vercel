# Catalyst — Automated Daily Edition (Vercel)

This is a **new, separate repo** hosted on **Vercel**, migrated from the
original GitHub Pages repo. It reuses the exact same Firebase project
(Firestore subscriber lists, email lists, Cloud Messaging) — nothing on the
backend/database side needs to be recreated, only the hosting layer and
GitHub Actions secrets are new (secrets don't carry over between repos).

**The old GitHub Pages repo stays live and untouched until this one is
fully verified working — only then should it be taken down.**

## Architecture (unchanged from the GitHub Pages version)

```
GitHub Actions (in THIS repo, own schedule/secrets)
  → generates content, sends notifications/email
  → commits data/ to THIS repo
        ↓
Vercel (connected to THIS repo)
  → auto-redeploys on every push
  → serves index.html, admin.html, data/*.json, icons/, manifest.json, sw.js
```

Vercel only ever serves static files — no backend code runs on it. All
generation, email, and push logic still runs on GitHub Actions, exactly as
before.

## Setup — step by step

### 1. Create the new GitHub repo and push this code
Standard `git init` / push to a new repo of your choice.

### 2. Re-add all GitHub secrets (they don't carry over from the old repo)
Settings → Secrets and variables → Actions → New repository secret, for
each of:
- `GEMINI_API_KEY` — same value as the old repo
- `PEXELS_API_KEY` — same value as the old repo
- `FIREBASE_SERVICE_ACCOUNT_JSON` — same value as the old repo (same
  Firebase project, so this is identical)
- `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` — same values as the old repo
- `SITE_URL` — leave for step 4, you don't have this yet

### 3. Connect the repo to Vercel
1. [vercel.com](https://vercel.com) → sign in with GitHub → **Add New →
   Project** → select this new repo
2. No config needed — Vercel auto-detects this as a static site → **Deploy**
3. Copy the URL Vercel gives you (e.g. `https://catalyst-yourname.vercel.app`)

### 4. Now add the SITE_URL secret
Using the URL from step 3, add the `SITE_URL` secret you skipped earlier.

### 5. Tell Firebase to trust the new domain
Firebase Console → Authentication → Settings → Authorized domains → Add
domain → paste the Vercel domain (no `https://`). Without this,
`admin.html` login will fail with `auth/unauthorized-domain`.

### 6. Test everything before touching the old repo
Run each workflow manually from the Actions tab in the new repo:
- `daily-edition.yml` → confirm green checkmark, site shows fresh content
- Visit the live site, click "🔔 Get daily alerts," confirm it subscribes
- `morning-notification.yml` → confirm a push actually arrives
- Visit `/admin.html`, sign in (same login as before, same Firebase Auth
  user), confirm your existing email lists are still there
- `email-digest.yml` → confirm the email arrives
- `evening-reminder.yml` → confirm the second push arrives

### 7. Only after all of the above genuinely works
Disable or delete the old GitHub Pages repo's workflows first (to stop
double-sending notifications/emails from both repos), confirm the new repo
keeps running fine on its own for a day or two, then delete the old repo.

## Custom domain (optional, same steps either way)
If you later add a custom domain (e.g. via GitHub Student Pack — see
earlier discussion), add it in Vercel → Project → Settings → Domains, then
repeat steps 4 and 5 with that domain instead.

## Costs
Unchanged: GitHub Actions, Vercel Hobby plan, Gemini API, Pexels API,
Firebase Spark plan, and Gmail SMTP are all free at this scale.
