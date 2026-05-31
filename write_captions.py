"""Caption pipeline in two phases (CLIs are driven by bash in between).

  python write_captions.py build     -> writes job prompt files + jobs.json
  (bash loop calls gemini/codex, saving stdout to out/<id>.txt)
  python write_captions.py collect   -> parses outputs, fills manifest.json

No em-dashes (enforced in prompt + scrubbed).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "manifest.json")
JOBDIR = os.path.join(HERE, ".capjobs")
OUTDIR = os.path.join(HERE, ".capout")
BATCH = 12

PROMPT_HEAD = """You write Instagram captions for "Sober Thoughts", a recovery and sobriety app (handle @soberthoughts.app). The app sends a calming daily thought to the user's home screen. Audience: people in recovery from alcohol or addiction.

For each quote below, write one Instagram caption. Rules:
- Warm, grounding, supportive voice. Never preachy or clinical.
- Honor the quote's mode: "spiritual" may gently reference faith or a higher power; "secular" uses NO religious language; "mindful" stays present-moment; "universal" stays broad.
- Vary your openings across the batch. Do not start every caption the same way.
- Structure: a short hook line, 2 to 3 short supportive lines, then a soft mention of the Sober Thoughts app with "link in bio", then one engagement question.
- ABSOLUTELY NO em-dashes or en-dashes. Use periods and commas only.
- End with 18 to 20 hashtags mixing big and niche recovery tags, always include #soberthoughts. Make tags relevant to the quote's mode.
- Keep under 2000 characters.

Output ONLY a valid JSON array, no markdown, no commentary. Each item: {"id": "...", "caption": "...", "hashtags": ["#tag1", ...]}. Put the caption text WITHOUT the hashtags in "caption"; hashtags go only in the array.

QUOTES:
"""


def build():
    os.makedirs(JOBDIR, exist_ok=True)
    os.makedirs(OUTDIR, exist_ok=True)
    manifest = json.load(open(MANIFEST, encoding="utf-8"))
    todo = [e for e in manifest if not e.get("caption")]
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    jobs = []
    for bi, batch in enumerate(batches):
        engine = "gemini" if bi % 2 == 0 else "codex"
        payload = [{"id": e["id"], "mode": e["mode"], "quote": e["quote_text"]}
                   for e in batch]
        prompt = PROMPT_HEAD + json.dumps(payload, ensure_ascii=False, indent=1)
        jid = f"{bi:02d}"
        with open(os.path.join(JOBDIR, f"{jid}.txt"), "w", encoding="utf-8") as f:
            f.write(prompt)
        jobs.append({"id": jid, "engine": engine, "n": len(batch)})
    json.dump(jobs, open(os.path.join(JOBDIR, "jobs.json"), "w"), indent=2)
    print(f"built {len(jobs)} jobs ({len(todo)} captions) in {JOBDIR}")


def _extract(text):
    i, j = text.find("["), text.rfind("]")
    if i == -1 or j == -1:
        raise ValueError("no JSON array")
    return json.loads(text[i:j + 1])


def _scrub(s):
    return s.replace("—", ", ").replace("–", ", ")


def collect():
    manifest = json.load(open(MANIFEST, encoding="utf-8"))
    by_id = {e["id"]: e for e in manifest}
    jobs = json.load(open(os.path.join(JOBDIR, "jobs.json")))
    done = 0
    for job in jobs:
        path = os.path.join(OUTDIR, f"{job['id']}.txt")
        if not os.path.exists(path):
            print(f"  job {job['id']} ({job['engine']}): no output")
            continue
        try:
            data = _extract(open(path, encoding="utf-8", errors="replace").read())
        except Exception as ex:
            print(f"  job {job['id']} ({job['engine']}) parse FAIL: {ex}")
            continue
        for d in data:
            cid = d.get("id")
            if cid in by_id:
                by_id[cid]["caption"] = _scrub((d.get("caption") or "").strip())
                by_id[cid]["hashtags"] = list(d.get("hashtags") or [])
                by_id[cid]["engine"] = job["engine"]
                done += 1
    json.dump(manifest, open(MANIFEST, "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    missing = [e["id"] for e in manifest if not e.get("caption")]
    print(f"collected {done}. missing {len(missing)}: {missing}")


if __name__ == "__main__":
    {"build": build, "collect": collect}[sys.argv[1]]()
