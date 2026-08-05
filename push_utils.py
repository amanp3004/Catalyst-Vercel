"""
push_utils.py — shared helpers for sending push notifications via Firebase
Cloud Messaging, with subscriber tokens stored in Firestore.

Requires the FIREBASE_SERVICE_ACCOUNT_JSON environment variable to contain
the full contents of a Firebase service account key JSON file (Project
Settings → Service Accounts → Generate new private key).
"""

import os
import json

import firebase_admin
from firebase_admin import credentials, firestore, messaging


def _init_firebase():
    if firebase_admin._apps:
        return
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise SystemExit(
            "FIREBASE_SERVICE_ACCOUNT_JSON environment variable is not set.\n"
            "Get it from Firebase Console → Project Settings → Service "
            "Accounts → Generate new private key."
        )
    cred_dict = json.loads(raw)
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)


def get_subscriber_tokens():
    _init_firebase()
    db = firestore.client()
    docs = db.collection("subscribers").stream()
    return [doc.id for doc in docs]


def remove_dead_token(token):
    _init_firebase()
    db = firestore.client()
    db.collection("subscribers").document(token).delete()


def send_push(title, body, click_url, tokens=None):
    """Send a push notification to all (or given) subscriber tokens.
    Automatically cleans up tokens that are no longer valid (e.g. the user
    uninstalled or revoked permission)."""
    _init_firebase()

    if tokens is None:
        tokens = get_subscriber_tokens()

    if not tokens:
        print("No subscribers yet — nothing to send.")
        return

    sent, failed = 0, 0
    for token in tokens:
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={"url": click_url},
            token=token,
        )
        try:
            messaging.send(message)
            sent += 1
        except (messaging.UnregisteredError, messaging.SenderIdMismatchError):
            remove_dead_token(token)
            failed += 1
        except Exception as e:
            print(f"[warn] Failed to send to a token: {e}")
            failed += 1

    print(f"Push sent: {sent} succeeded, {failed} failed/cleaned up.")
