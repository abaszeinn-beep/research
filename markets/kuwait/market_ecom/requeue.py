"""Send candidates whose last verification failed for a transient reason back to the verifier queue.

  python3 -m market_ecom.requeue [--max-attempts 3]
"""
import argparse

from . import db

TRANSIENT = ("dns_not_resolved%", "fetch_failed:connect_error%", "fetch_failed:timeout%", "fetch_failed:browser_error%",
             "rate_limited%", "browser_verifier_error%", "verifier_error%")


def main(max_attempts):
    con = db.connect()
    cond = " OR ".join("v.reason LIKE ?" for _ in TRANSIENT)
    n = con.execute(
        f"UPDATE candidates SET status='pending' WHERE status IN ('unverified','rejected') AND attempts < ? AND key IN "
        f"(SELECT key FROM verifications v WHERE {cond})", (max_attempts, *TRANSIENT)).rowcount
    con.commit()
    print(f"[requeue] {n} candidates back to pending", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-attempts", type=int, default=3)
    main(ap.parse_args().max_attempts)
