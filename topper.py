"""Daily poster for the Sober Thoughts IG queue.

Posts the next `backlog` card to Instagram via the Meta Graph API, then marks
it `posted` in manifest.json. Designed to run once/day from GitHub Actions, so
the cron *is* the schedule (no Buffer, no always-on machine).

Env vars (set as GitHub Actions Secrets):
  IG_USER_ID        Instagram business user id
  IG_ACCESS_TOKEN   long-lived Instagram token
  REPO_RAW_BASE     e.g. https://raw.githubusercontent.com/<user>/<repo>/main

Image hosting: cards live in this public repo, served via raw.githubusercontent.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "manifest.json")
GRAPH = "https://graph.instagram.com/v21.0"


def _read(resp):
    return json.loads(resp.read().decode())


def _err(e):
    body = e.read().decode()
    try:
        return json.loads(body)
    except Exception:
        return {"error": {"message": body, "http_status": e.code}}


def _post(url, params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return _read(r)
    except urllib.error.HTTPError as e:
        return _err(e)


def _get(url, params):
    q = urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(f"{url}?{q}", timeout=60) as r:
            return _read(r)
    except urllib.error.HTTPError as e:
        return _err(e)


def caption_text(entry):
    tags = " ".join(entry.get("hashtags", []))
    return f"{entry['caption']}\n\n{tags}".strip()


def main():
    ig_id = os.environ["IG_USER_ID"]
    token = os.environ["IG_ACCESS_TOKEN"]
    raw_base = os.environ["REPO_RAW_BASE"].rstrip("/")

    manifest = json.load(open(MANIFEST, encoding="utf-8"))
    backlog = [e for e in manifest if e.get("status") == "backlog"]
    if not backlog:
        print("Queue empty. Nothing to post.")
        return
    entry = sorted(backlog, key=lambda e: e["id"])[0]
    image_url = f"{raw_base}/{entry['card_file']}"
    caption = caption_text(entry)

    print(f"Posting card {entry['id']} ({entry['mode']}) -> {image_url}")

    # 1. create media container
    container = _post(f"{GRAPH}/{ig_id}/media", {
        "image_url": image_url, "caption": caption, "access_token": token,
    })
    cid = container.get("id")
    if not cid:
        print("Container creation failed:", container, file=sys.stderr)
        sys.exit(1)

    # 2. wait for Meta to fetch + process the image (container -> FINISHED)
    for _ in range(12):
        st = _get(f"{GRAPH}/{cid}", {
            "fields": "status_code", "access_token": token})
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code == "ERROR":
            print("Container processing ERROR:", st, file=sys.stderr)
            sys.exit(1)
        time.sleep(6)

    # 3. publish (retry while still settling)
    media = {}
    for _ in range(5):
        media = _post(f"{GRAPH}/{ig_id}/media_publish", {
            "creation_id": cid, "access_token": token,
        })
        if media.get("id"):
            break
        print("  publish not ready:", media.get("error", {}).get("message", media))
        time.sleep(8)
    mid = media.get("id")
    if not mid:
        print("Publish failed:", media, file=sys.stderr)
        sys.exit(1)

    # 3. fetch permalink (best effort)
    permalink = ""
    try:
        permalink = _get(f"{GRAPH}/{mid}", {
            "fields": "permalink", "access_token": token}).get("permalink", "")
    except Exception:
        pass

    entry["status"] = "posted"
    entry["posted_media_id"] = mid
    entry["posted_at"] = datetime.now(timezone.utc).isoformat()
    entry["permalink"] = permalink
    json.dump(manifest, open(MANIFEST, "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)

    remaining = sum(1 for e in manifest if e.get("status") == "backlog")
    print(f"POSTED {entry['id']}  media={mid}  {permalink}")
    print(f"Backlog remaining: {remaining}")


if __name__ == "__main__":
    main()
