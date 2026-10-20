"""Run wb_probe over named storefront prefixes sequentially; JSON lines to data/wb_batch.jsonl (resumable by name)."""
import asyncio, json, os, sys
from .wb_probe import probe

CONF = [
 ("Adidas", "adidas.ae/en/", r".*\.html"),
 ("Babyshop", "babyshopstores.com/ae/", r".*(/p/|\.html|/product|-[0-9]{6,}).*"),
 ("Boots", "boots.ae/", r".*(/p/|\.html|/product|/en/).*"),
 ("Dubai Duty Free", "dubaidutyfree.com/", r".*(/p/|\.html|/product|/shop|/liquor|/electronics).*"),
 ("H&M", "www2.hm.com/en_ae/", r".*productpage.*"),
 ("Huda Beauty", "hudabeauty.com/ae/", r".*\.html"),
 ("Joyalukkas", "joyalukkas.com/ae/", r".*\.html"),
 ("Lulu", "luluhypermarket.com/en-ae/", r".*"),
 ("Malabar", "malabargoldanddiamonds.com/ae/", r".*\.html"),
 ("Namshi", "namshi.com/uae-en/", r".*(/buy-|/p/).*"),
 ("Sharaf DG", "sharafdg.com/", r".*(/product|/p/|\.html).*"),
 ("Shoemart", "shoemartstores.com/ae/", r".*"),
 ("Styli", "stylishop.com/ae/en/", r".*\.html"),
]
async def main():
    path = "data/wb_batch.jsonl"
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
