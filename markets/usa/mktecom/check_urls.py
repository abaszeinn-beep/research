"""Ad-hoc: verify a list of URLs without touching the DB (for QA / debugging)."""
import asyncio, json, sys, warnings
from .verify import Fetcher, verify_one
from .common import identity
warnings.filterwarnings("ignore")

async def main(urls):
    f = Fetcher(16, 2)
    async def one(u):
        ident = identity(u)
        if not ident:
            return u, None
        return u, await verify_one(f, ident)
    for u, r in await asyncio.gather(*[one(u) for u in urls]):
        if r is None:
            print(u, "-> no identity"); continue
        print(f"{u}\n   {r['status']:10s} {r['reason'][:90]} | name={r['store_name'][:30]} plat={r['platform']} cat={r['category']} score={r.get('market_score')} final={r['final_url'][:60]} t={r.get('elapsed')}")
        print('   market:', r.get('market_evidence','')[:300], '| ecom:', r.get('ecom_evidence','')[:200])

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
