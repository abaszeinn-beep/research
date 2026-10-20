"""Append one proposed correction to data/qa/corrections_work.jsonl (reviewer working file).

  python3 scripts/qa_corr.py KEY CURRENT CORRECTED CATEGORY PASS "reason" EVIDENCE_URL [NAME]
"""
import datetime as dt, json, sys
key, cur, new, cat, passname, reason, ev = sys.argv[1:8]
name = sys.argv[8] if len(sys.argv) > 8 else ""
rec = {"key": key, "store_name": name, "current_status": cur, "corrected_status": new, "category": cat, "pass": passname,
       "reason": reason, "evidence_url": ev, "reviewed_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
with open("data/qa/corrections_work.jsonl", "a") as f:
    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
print("ok", key, cur, "->", new)
