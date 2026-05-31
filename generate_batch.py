"""Generate a batch of Sober Thoughts IG quote cards + a manifest.

- Picks a balanced, diverse set of quotes from the app's seed.json
- Mood-matches a wallpaper to each quote's content mode
- Renders 4:5 cards into cards/
- Writes manifest.json (status=backlog; captions filled in a later step)

Run: python generate_batch.py [count]
"""
import json
import os
import sys

from make_card import render_card

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = r"C:\Users\Facundo\Projects\sober-thoughts\content\seed.json"
WP_DIR = r"C:\Users\Facundo\Projects\sober-thoughts\assets\wallpapers"
CARDS = os.path.join(HERE, "cards")
MANIFEST = os.path.join(HERE, "manifest.json")

# wallpaper pools by mood (filename stems; matched by substring)
POOLS = {
    "spiritual": ["cross-sunrise", "sacred-geometry", "olive-tree",
                  "floating-lanterns", "ancient-tree", "stone-arch",
                  "garden-labyrinth", "village-dawn"],
    "mindful": ["zen-garden", "bamboo-forest", "kintsugi", "meditation-room",
                "morning-tea", "pottery-wheel", "beach-reflection", "fog-valley",
                "lavender-field", "still-lake-boat"],
    "secular": ["neural-paths", "desert-stars", "underwater-rising",
                "compass-map", "hourglass", "aurora", "lighthouse",
                "open-door", "single-match", "butterfly-emerging"],
    "universal": ["dawn-forest", "sunset-cliff", "garden-path", "mountain-sunrise",
                  "wheat-field", "canyon-river", "waterfall", "starry-lake",
                  "cliff-stairs", "autumn-forest", "sunflowers", "bridge-together",
                  "hot-air-balloon", "autumn-river", "seedling-hands", "ocean-anchor",
                  "winter-cabin", "rain-cabin"],
}

GOOD_CATEGORIES = {"daily_affirmations", "recovery_wisdom", "morning_intentions"}


def mode_of(q):
    if q.get("is_spiritual"):
        return "spiritual"
    if q.get("is_mindful"):
        return "mindful"
    if q.get("is_secular"):
        return "secular"
    return "universal"


def resolve_wallpapers():
    """Map pool stems to actual files that exist."""
    files = [f for f in os.listdir(WP_DIR) if f.lower().endswith(".png")]
    out = {}
    for mood, stems in POOLS.items():
        matched = []
        for stem in stems:
            for f in files:
                if stem in f:
                    matched.append(f)
                    break
        out[mood] = matched or files
    return out


def select_quotes(seed, count):
    """Balanced, deterministic, varied selection."""
    pool = [q for q in seed
            if q["length_type"] in ("short", "medium")
            and q["category"] in GOOD_CATEGORIES]
    by_mode = {"universal": [], "spiritual": [], "secular": [], "mindful": []}
    for q in pool:
        by_mode[mode_of(q)].append(q)
    for m in by_mode:
        by_mode[m].sort(key=lambda q: q["id"])  # deterministic
    # target mix
    targets = {"universal": int(count * 0.46), "spiritual": int(count * 0.18),
               "secular": int(count * 0.18), "mindful": int(count * 0.18)}
    while sum(targets.values()) < count:
        targets["universal"] += 1
    picked = []
    for m, n in targets.items():
        src = by_mode[m]
        if not src:
            continue
        stride = max(1, len(src) // max(1, n))   # spread across the pool
        chosen = src[::stride][:n]
        picked.extend(chosen)
    # de-dupe and trim
    seen, final = set(), []
    for q in picked:
        if q["id"] in seen:
            continue
        seen.add(q["id"])
        final.append(q)
    return final[:count]


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    seed = json.load(open(SEED, encoding="utf-8"))
    wps = resolve_wallpapers()
    quotes = select_quotes(seed, count)

    rot = {m: 0 for m in wps}      # rotation index per pool
    last_wp = None
    manifest = []
    for i, q in enumerate(quotes, 1):
        m = mode_of(q)
        pool = wps[m]
        wp = pool[rot[m] % len(pool)]
        if wp == last_wp and len(pool) > 1:      # avoid back-to-back repeat
            rot[m] += 1
            wp = pool[rot[m] % len(pool)]
        rot[m] += 1
        last_wp = wp

        cid = f"{i:03d}"
        card_file = f"cards/{cid}_{q['id']}.png"
        render_card(q["quote_text"], os.path.join(WP_DIR, wp),
                    os.path.join(HERE, card_file))
        manifest.append({
            "id": cid,
            "quote_id": q["id"],
            "quote_text": q["quote_text"],
            "mode": m,
            "category": q["category"],
            "topics": q.get("topics", []),
            "wallpaper": wp,
            "card_file": card_file,
            "caption": "",
            "hashtags": [],
            "status": "backlog",
        })
        if i % 10 == 0:
            print(f"  rendered {i}/{len(quotes)}")

    json.dump(manifest, open(MANIFEST, "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    # mode tally
    tally = {}
    for e in manifest:
        tally[e["mode"]] = tally.get(e["mode"], 0) + 1
    print(f"DONE: {len(manifest)} cards. modes={tally}")


if __name__ == "__main__":
    main()
