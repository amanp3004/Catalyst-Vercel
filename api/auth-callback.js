// api/auth-callback.js — the redirect_uri Google sends the user back to
// after they approve sign-in. Runs entirely server-side: exchanges the
// authorization code for the user's real identity, mints a Firebase
// custom token, and hands it to the client via a URL fragment.
//
// Why this exists instead of just using Firebase's own signInWithRedirect:
// that relies on IndexedDB-based state written right before the page
// navigates away, and there are documented, unresolved bugs where that
// write doesn't reliably commit inside an installed standalone PWA on
// both iOS and Android. This flow needs no client-side storage to survive
// the round trip at all — the authorization code arrives as a plain URL
// query parameter, and the resulting custom token leaves the same way,
// via a URL fragment. Nothing here depends on IndexedDB/localStorage
// surviving the navigation.
//
// Requires these Vercel environment variables (Project Settings →
// Environment Variables — NOT the same place as GitHub Actions secrets,
// these must be added separately):
//   GOOGLE_OAUTH_CLIENT_ID       — from Google Cloud Console
//   GOOGLE_OAUTH_CLIENT_SECRET   — from Google Cloud Console (server-only, never sent to the client)
//   FIREBASE_SERVICE_ACCOUNT_JSON — same JSON already used for the GitHub Actions secret

const admin = require("firebase-admin");

if (!admin.apps.length) {
  admin.initializeApp({
    credential: admin.credential.cert(JSON.parse(process.env.FIREBASE_SERVICE_ACCOUNT_JSON)),
  });
}

module.exports = async (req, res) => {
  const { code, error } = req.query;

  if (error) {
    // The user cancelled, or Google itself rejected the request.
    res.redirect(302, `/app.html?authError=${encodeURIComponent(String(error))}`);
    return;
  }
  if (!code) {
    res.status(400).send("Missing authorization code.");
    return;
  }

  try {
    // redirect_uri here MUST exactly match what's registered in Google
    // Cloud Console and what the client used to build the original
    // authorization URL — Google rejects the exchange otherwise.
    const redirectUri = `https://${req.headers.host}/api/auth-callback`;

    const tokenRes = await fetch("https://oauth2.googleapis.com/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        code: String(code),
        client_id: process.env.GOOGLE_OAUTH_CLIENT_ID,
        client_secret: process.env.GOOGLE_OAUTH_CLIENT_SECRET,
        redirect_uri: redirectUri,
        grant_type: "authorization_code",
      }),
    });
    const tokenData = await tokenRes.json();
    if (!tokenData.id_token) {
      throw new Error("Google token exchange failed: " + JSON.stringify(tokenData));
    }

    // Verify the ID token via Google's own tokeninfo endpoint. This is a
    // simple HTTP call rather than pulling in a JWT verification library
    // — sufficient here since we're only reading identity fields, not
    // making any security decision that depends on signature timing.
    const verifyRes = await fetch(`https://oauth2.googleapis.com/tokeninfo?id_token=${tokenData.id_token}`);
    const payload = await verifyRes.json();
    if (payload.aud !== process.env.GOOGLE_OAUTH_CLIENT_ID) {
      throw new Error("Token audience mismatch — possible token substitution.");
    }
    if (!payload.email || payload.email_verified !== "true") {
      throw new Error("Google account email is missing or unverified.");
    }

    const email = payload.email;
    const name = payload.name || "";
    const picture = payload.picture || "";

    // Reuse the same Firebase user if one already exists for this email
    // (e.g. from an earlier desktop sign-in via the normal popup flow) —
    // otherwise every mobile sign-in would create a second, disconnected
    // identity for the same real person, fragmenting their bookmarks
    // across two different Firebase uids.
    let userRecord;
    try {
      userRecord = await admin.auth().getUserByEmail(email);
    } catch (e) {
      userRecord = await admin.auth().createUser({ email, displayName: name, photoURL: picture });
    }

    const customToken = await admin.auth().createCustomToken(userRecord.uid);
    res.redirect(302, `/app.html#customToken=${encodeURIComponent(customToken)}`);
  } catch (err) {
    console.error("Auth callback error:", err);
    res.redirect(302, `/app.html?authError=${encodeURIComponent(err.message)}`);
  }
};
