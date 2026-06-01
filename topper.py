"""Sober Thoughts Instagram auto-poster.

Reads the next backlog item from manifest.json, publishes it to Instagram via the
Meta Graph API, and marks the manifest entry as posted on success.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


API_BASE = "https://graph.instagram.com/v21.0"
MAX_STATUS_POLLS = 12
STATUS_POLL_SLEEP_SECONDS = 5
PUBLISH_RETRIES = 5
PUBLISH_RETRY_SLEEP_SECONDS = 5


class MetaAPIError(Exception):
    """Raised when Meta returns an API error or an unexpected response."""


def stderr(message: str) -> None:
    print(message, file=sys.stderr)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_today_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def posted_at_utc_date(entry: dict[str, Any]) -> str | None:
    posted_at = entry.get("posted_at")
    if not isinstance(posted_at, str):
        return None

    value = posted_at.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(value).astimezone(timezone.utc).date().isoformat()
    except ValueError:
        return None


def already_posted_today(manifest: list[dict[str, Any]]) -> bool:
    today = utc_today_date()
    return any(posted_at_utc_date(entry) == today for entry in manifest)


def load_manifest(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except FileNotFoundError as exc:
        raise RuntimeError(f"manifest.json not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"manifest.json is not valid JSON: {exc}") from exc

    if not isinstance(manifest, list):
        raise RuntimeError("manifest.json must contain a JSON list")

    return manifest


def save_manifest(path: Path, manifest: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def parse_meta_error(body: bytes, fallback: str) -> str:
    if not body:
        return fallback

    text = body.decode("utf-8", errors="replace")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text or fallback

    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        code = error.get("code")
        error_type = error.get("type")
        error_subcode = error.get("error_subcode")

        parts = []
        if message:
            parts.append(str(message))
        if error_type:
            parts.append(f"type={error_type}")
        if code is not None:
            parts.append(f"code={code}")
        if error_subcode is not None:
            parts.append(f"subcode={error_subcode}")

        return "Meta API error: " + ", ".join(parts) if parts else json.dumps(error, ensure_ascii=False)

    return text or fallback


def request_json(method: str, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    url = path_or_url if path_or_url.startswith("http") else API_BASE + path_or_url

    encoded_params = urllib.parse.urlencode(params, doseq=True).encode("utf-8")

    if method.upper() == "GET":
        if encoded_params:
            separator = "&" if "?" in url else "?"
            url = url + separator + encoded_params.decode("utf-8")
        data = None
    else:
        data = encoded_params

    request = urllib.request.Request(url, data=data, method=method.upper())
    if data is not None:
        request.add_header("Content-Type", "application/x-www-form-urlencoded; charset=utf-8")

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response_body = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read()
        raise MetaAPIError(parse_meta_error(body, f"HTTP {exc.code}: {exc.reason}")) from exc
    except urllib.error.URLError as exc:
        raise MetaAPIError(f"Network error: {exc.reason}") from exc

    if not response_body:
        return {}

    try:
        payload = json.loads(response_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise MetaAPIError(f"Meta returned non-JSON response: {response_body.decode('utf-8', errors='replace')}") from exc

    if isinstance(payload, dict) and "error" in payload:
        raise MetaAPIError(parse_meta_error(response_body, "Meta API error"))

    if not isinstance(payload, dict):
        raise MetaAPIError(f"Meta returned unexpected JSON response: {payload!r}")

    return payload


def pick_next_backlog(manifest: list[dict[str, Any]]) -> dict[str, Any] | None:
    backlog = [entry for entry in manifest if entry.get("status") == "backlog"]
    if not backlog:
        return None
    return sorted(backlog, key=lambda entry: str(entry.get("id", "")))[0]


def validate_entry(entry: dict[str, Any]) -> None:
    required_fields = ("id", "card_file", "caption", "hashtags", "status")
    missing = [field for field in required_fields if field not in entry]
    if missing:
        raise RuntimeError(f"Manifest entry is missing required field(s): {', '.join(missing)}")

    if not isinstance(entry["hashtags"], list) or not all(isinstance(tag, str) for tag in entry["hashtags"]):
        raise RuntimeError(f"Manifest entry {entry.get('id')} has invalid hashtags; expected list of strings")


def create_container(user_id: str, image_url: str, caption: str, access_token: str) -> str:
    payload = request_json(
        "POST",
        f"/{urllib.parse.quote(user_id)}/media",
        {
            "image_url": image_url,
            "caption": caption,
            "access_token": access_token,
        },
    )

    container_id = payload.get("id")
    if not container_id:
        raise MetaAPIError(f"Meta did not return a creation container id: {payload}")

    return str(container_id)


def wait_for_container(container_id: str, access_token: str) -> None:
    quoted_container_id = urllib.parse.quote(container_id)

    for attempt in range(1, MAX_STATUS_POLLS + 1):
        payload = request_json(
            "GET",
            f"/{quoted_container_id}",
            {
                "fields": "status_code",
                "access_token": access_token,
            },
        )

        status = payload.get("status_code")
        if status == "FINISHED":
            return
        if status in {"ERROR", "EXPIRED"}:
            raise MetaAPIError(f"Creation container {container_id} ended with status_code={status}: {payload}")

        if attempt < MAX_STATUS_POLLS:
            time.sleep(STATUS_POLL_SLEEP_SECONDS)

    raise MetaAPIError(f"Creation container {container_id} was not ready after {MAX_STATUS_POLLS} polls")


def publish_media(user_id: str, container_id: str, access_token: str) -> str:
    last_error: Exception | None = None

    for attempt in range(1, PUBLISH_RETRIES + 1):
        try:
            payload = request_json(
                "POST",
                f"/{urllib.parse.quote(user_id)}/media_publish",
                {
                    "creation_id": container_id,
                    "access_token": access_token,
                },
            )
            media_id = payload.get("id")
            if not media_id:
                raise MetaAPIError(f"Meta did not return a published media id: {payload}")
            return str(media_id)
        except MetaAPIError as exc:
            last_error = exc
            if attempt < PUBLISH_RETRIES:
                time.sleep(PUBLISH_RETRY_SLEEP_SECONDS)

    raise MetaAPIError(f"Media publish failed after {PUBLISH_RETRIES} attempts: {last_error}")


def get_permalink(media_id: str, access_token: str) -> str:
    try:
        payload = request_json(
            "GET",
            f"/{urllib.parse.quote(media_id)}",
            {
                "fields": "permalink",
                "access_token": access_token,
            },
        )
    except MetaAPIError as exc:
        stderr(f"Warning: could not fetch permalink: {exc}")
        return ""

    permalink = payload.get("permalink")
    return str(permalink) if permalink else ""


def main() -> int:
    try:
        script_dir = Path(__file__).resolve().parent
        manifest_path = script_dir / "manifest.json"

        ig_user_id = required_env("IG_USER_ID")
        access_token = required_env("IG_ACCESS_TOKEN")
        raw_base = required_env("REPO_RAW_BASE").rstrip("/")

        manifest = load_manifest(manifest_path)

        if not env_flag("FORCE_POST") and already_posted_today(manifest):
            print(f"A card has already been posted for UTC date {utc_today_date()}; skipping.")
            return 0

        entry = pick_next_backlog(manifest)
        if entry is None:
            print("No backlog entries remaining.")
            return 0

        validate_entry(entry)

        card_file = str(entry["card_file"]).lstrip("/")
        image_url = f"{raw_base}/{card_file}"
        caption = str(entry["caption"]) + "\n\n" + " ".join(str(tag) for tag in entry["hashtags"])

        container_id = create_container(ig_user_id, image_url, caption, access_token)
        wait_for_container(container_id, access_token)
        media_id = publish_media(ig_user_id, container_id, access_token)
        permalink = get_permalink(media_id, access_token)

        entry["status"] = "posted"
        entry["posted_media_id"] = media_id
        entry["posted_at"] = utc_now_iso()
        entry["permalink"] = permalink

        save_manifest(manifest_path, manifest)

        remaining = sum(1 for item in manifest if item.get("status") == "backlog")
        print(permalink or media_id)
        print(f"Remaining backlog count: {remaining}")
        return 0

    except (RuntimeError, MetaAPIError) as exc:
        stderr(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())

