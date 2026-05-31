# Sober Thoughts — Instagram auto-poster

Free, serverless Instagram posting pipeline for [@soberthoughts.app](https://instagram.com/soberthoughts.app).
Generates branded quote cards, writes captions, and posts one per day from
GitHub Actions. No always-on machine, no paid scheduler.

## How it works

```
quotes (seed.json) + wallpapers
        |  generate_batch.py        -> 100 quote cards (cards/) + manifest.json
        |  write_captions.py        -> captions via Gemini + Codex (no em-dashes)
        v
manifest.json  (the queue: status backlog -> posted)
        |
GitHub Actions (daily cron, free)
        |  topper.py                -> posts next backlog card via Meta Graph API
        v
   Instagram
```

- **Image hosting:** cards live in this public repo, served free via
  `raw.githubusercontent.com`. Meta fetches the image by URL.
- **The cron is the schedule.** Posts 1 card/day at 15:00 UTC (8am PT). 100
  cards = ~3 months of content. Re-run the generator to refill.

## Setup (one time)

1. Push this repo to GitHub (public, for raw image hosting).
2. Repo **Settings -> Secrets and variables -> Actions -> New repository secret**:
   - `IG_USER_ID` — Instagram business user id
   - `IG_ACCESS_TOKEN` — long-lived Instagram token (expires every 60 days, refresh + update this secret)
3. Done. The workflow runs daily. Trigger manually anytime via
   **Actions -> Daily IG Post -> Run workflow**.

## Regenerating content

```bash
pip install Pillow
python generate_batch.py 100      # render cards + manifest
python write_captions.py build    # build caption jobs
# drive CLIs (bash):
while read id engine; do
  [ "$engine" = gemini ] && gemini -p "$(cat .capjobs/$id.txt)" > .capout/$id.txt 2>/dev/null </dev/null \
                         || codex exec --skip-git-repo-check "$(cat .capjobs/$id.txt)" > .capout/$id.txt 2>/dev/null </dev/null
done < <(python -c "import json;[print(j['id'],j['engine']) for j in json.load(open('.capjobs/jobs.json'))]")
python write_captions.py collect  # fill manifest
```

## Token refresh (every 60 days)

```bash
curl "https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=OLD_TOKEN"
```

Update the `IG_ACCESS_TOKEN` secret with the returned token.
