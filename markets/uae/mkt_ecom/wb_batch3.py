"""Run wb_probe over named storefront prefixes sequentially; JSON lines to data/wb_batch3.jsonl (resumable by name)."""
import asyncio, json, os, sys
from .wb_probe import probe

CONF = [
 ("Carrefour", "carrefouruae.com/mafuae/en/", r".*/p/.*"),
 ("Huda Beauty", "hudabeauty.com/", r".*(en-ae|ar-ae)/products/.*"),
 ("Lulu", "luluhypermarket.com/", r".*(/p/|/pd/|/product|[0-9]{5,}).*"),
 ("Lulu2", "luluhypermarket.com/en-ae/", r".*"),
 ("Boots", "boots.ae/", r".*"),
 ("Boots2", "boots.com/", r".*(/en_ae|/ae/).*"),
 ("H&M", "hm.com/", r".*en_ae.*"),
]
async def main():
    path = "data/wb_batch3.jsonl"
    done = set()
    if os.path.exists(path):
        done = {json.loads(l)["name"] for l in open(path) if l.strip() and not json.loads(l).get("error")}
    for name, prefix, rx in CONF:
        if name in done:
            continue
        r = await probe(prefix, rx, 4)
        r["name"] = name
        open(path, "a").write(json.dumps(r, ensure_ascii=False) + "\n")
        print(name, r.get("error"), r["captures"], bool(r["ok"]), flush=True)
asyncio.run(main())
