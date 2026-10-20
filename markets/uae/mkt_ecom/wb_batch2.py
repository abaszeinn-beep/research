"""Run wb_probe over named storefront prefixes sequentially; JSON lines to data/wb_batch2.jsonl (resumable by name)."""
import asyncio, json, os, sys
from .wb_probe import probe

CONF = [
 ("H&M", "ae.hm.com/", r".*(productpage|/product).*"),
 ("H&M2", "www2.hm.com/", r".*en_ae.*productpage.*"),
 ("Lulu", "luluhypermarket.com/", r".*(en-ae|ar-ae).*(/p/|/pd/|/product|[0-9]{5,}).*"),
 ("Sharaf DG", "uae.sharafdg.com/", r".*(/product|/p/|\.html|-[0-9]+/?$).*"),
 ("Styli", "stylishop.com/ae/", r".*\.html"),
 ("Styli2", "stylishop.com/", r".*ae.*(/p/|\.html).*"),
 ("Huda Beauty", "hudabeauty.com/", r".*/products/.*"),
 ("Boots", "boots.ae/", r".*"),
 ("Joyalukkas", "joyalukkas.com/", r".*/ae/.*\.html"),
 ("Shoemart", "shoemartstores.com/ae/", r".*(/p/|\.html|/buy|/product|/c/).*"),
 ("Dubai Duty Free2", "dubaidutyfree.com/", r".*/product/.*"),
]
async def main():
    path = "data/wb_batch2.jsonl"
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
