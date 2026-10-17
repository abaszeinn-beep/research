"""Load the Tranco top-1M list and boost the priority of pending candidates by rank (idempotent)."""
import os, sys, csv, math
sys.path.insert(0, os.path.dirname(__file__))
from common import connect, registrable

path = sys.argv[1]
SHARED = {'uk.com','us.com','eu.com','co.com','de.com','za.com','ae.org','us.org','com.co','myshopify.com','shopify.com','blogspot.com','wixsite.com','weebly.com','square.site','github.io','netlify.app','vercel.app'}
con = connect()
con.execute("CREATE TABLE IF NOT EXISTS tranco(domain TEXT PRIMARY KEY, rank INTEGER)")
con.execute("DELETE FROM tranco")
con.executemany("INSERT OR REPLACE INTO tranco VALUES(?,?)",
                ((d.strip().lower(), int(r)) for r, d in csv.reader(open(path))))
con.commit()
rk = dict(con.execute("SELECT domain, rank FROM tranco"))
con.execute("CREATE TABLE IF NOT EXISTS prio_base(key TEXT PRIMARY KEY, base REAL)")
con.execute("INSERT OR IGNORE INTO prio_base SELECT key, priority FROM candidates")
upd = []
for key, base in con.execute("SELECT c.key, b.base FROM candidates c JOIN prio_base b USING(key) WHERE c.state IN ('pending','claimed')"):
    r = rk.get(key) or rk.get(key[4:] if key.startswith('www.') else '') or (rk.get(registrable(key)) if registrable(key) not in SHARED else None)
    if r:
        bonus = 12 - 2 * math.log10(r)  # rank 1k -> +6, 100k -> +2, 1M -> 0 (plus constant)
        upd.append((base + bonus + 1.0, key))
    else:
        upd.append((base, key))
con.executemany("UPDATE candidates SET priority=? WHERE key=?", upd)
con.execute("UPDATE candidates SET state='pending' WHERE state='claimed'")
con.commit()
print('updated', len(upd))
