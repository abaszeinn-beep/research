"""Merge deep gap-fill agent outputs (/tmp/prospects/gap_out) into the final Gulf datasets.

Rules (see /tmp/prospects/SPEC.md): never construct contacts, exclude support-type mailboxes,
blank = "Not found". Existing verified values are never overwritten, except the explicit
LinkedIn corrections in LINKEDIN_OVERRIDES that the gap agents documented in their logs.
"""
import glob
import re
import shutil
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

ROOT = Path("/tmp/prospects")
GAP = ROOT / "gap_out"
BACKUP = ROOT / "final_pre_gap"
MARKETS = {"Saudi": "final_saudi", "UAE": "final_gulf", "Qatar": "final_gulf", "Kuwait": "final_gulf"}
GAP_GLOB = {"Saudi": "Saudi", "UAE": "UAE", "Qatar": "Qatar", "Kuwait": "Kuwait"}
NF = "Not found"
TODAY = "2026-10-22"

COMP_COLS = ["Root Domain", "Company Phone Numbers", "Company Emails", "Company LinkedIn",
             "Primary Decision Maker Name", "Position", "Sources", "Research Status", "Checked Date"]
PPL_COLS = ["Company Name", "Website Link", "Root Domain", "Contact Name", "Position", "Phone Numbers",
            "Email", "LinkedIn Profile", "Source Links", "Verification"]

BAD_MAILBOX = re.compile(r"^(support|help|care|returns?|orders?|customer[-_.]?(service|care)|noreply|no-reply|"
                         r"donotreply|privacy|careers?|jobs?|hr|recruitment|complaints?)@", re.I)

# Existing company LinkedIn pages that the gap agents documented as belonging to another entity.
LINKEDIN_CLEAR = {"gastronom.ae", "thecakelab.ae", "pharmacynearme.ae", "balloonfactory.ae"}
LINKEDIN_REPLACE = {"toycorner.ae", "urbandeco.ae"}

# Stores the agents explicitly flagged as not being online retail stores. Rows are kept in the
# workbooks (the spec has no rule for dropping them) but are excluded from coverage counts.
NON_STORE = {"informaconnect.com", "continentalclub.ae", "takweenaldar.ae", "getfit.ae",
             "fujfc.ae", "dibbaclub.ae", "fares8.sa"}


def rd(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def blank(v):
    v = (v or "").strip()
    return v == "" or v.lower().startswith("not found")


def host(u):
    u = (u or "").strip()
    if not re.match(r"https?://", u):
        u = "https://" + u
    h = urlparse(u).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def norm_name(n):
    n = re.sub(r"\(.*?\)", " ", n or "")
    n = re.sub(r",.*$", "", n)
    return re.sub(r"[^a-z\u0600-\u06ff ]", "", n.lower()).strip()


def digits(p):
    return re.sub(r"\D", "", p)


def split_list(v):
    return [x.strip() for x in re.split(r"[,;]", v) if x.strip()] if not blank(v) else []


def merge_phones(existing, new):
    out, seen = split_list(existing), set()
    for p in out:
        seen.add(digits(p))
    for p in split_list(new):
        d = digits(p)
        if d and d not in seen and len(d) >= 7:
            seen.add(d)
            out.append(p)
    return ", ".join(out) if out else NF


def merge_emails(existing, new):
    out, seen = split_list(existing), set()
    for e in out:
        seen.add(e.lower())
    for e in split_list(new):
        if "@" in e and e.lower() not in seen and not BAD_MAILBOX.match(e):
            seen.add(e.lower())
            out.append(e)
    return ", ".join(out) if out else NF


def urls(v):
    toks = re.split(r"[;|,\s]+", v or "")
    out = []
    for t in toks:
        t = t.strip()
        if re.match(r"https?://[^\s/]+\.[^\s/]+", t) and t not in out:
            out.append(t)
    return out


def clean_sources(v):
    return "; ".join(urls(v))


def li_slug(u):
    m = re.search(r"linkedin\.com/(company|in|showcase|school)/([^/?#]+)", u or "", re.I)
    return (m.group(1).lower(), m.group(2).lower().rstrip("/")) if m else None


def valid_company_li(u):
    return bool(re.match(r"https?://([a-z]{2,3}\.)?linkedin\.com/(company|showcase|school)/", u or ""))


def valid_person_li(u):
    return bool(re.match(r"https?://([a-z]{2,3}\.)?linkedin\.com/in/", u or ""))


def https_li(u):
    return re.sub(r"^http://", "https://", u.strip())


def resolve_key(raw, by_host, by_exact):
    if raw in by_exact:
        return raw
    cand = by_host.get(host(raw), [])
    return cand[0] if len(cand) == 1 else None


def run(market, report):
    final = ROOT / MARKETS[market]
    BACKUP.mkdir(exist_ok=True)
    for kind in ("companies", "people"):
        bak = BACKUP / f"{market}_{kind}.csv"
        if not bak.exists():
            shutil.copy(final / f"{market}_{kind}.csv", bak)
    comp = rd(BACKUP / f"{market}_companies.csv")
    ppl = rd(BACKUP / f"{market}_people.csv")
    comp = comp.set_index("Root Domain", drop=False)
    by_exact = set(comp.index)
    by_host = {}
    for k in comp.index:
        by_host.setdefault(host(k), []).append(k)
    st = Counter()

    gap_ppl = []
    for f in sorted(glob.glob(str(GAP / f"*{GAP_GLOB[market]}*_people.csv"))):
        if "work" in f:
            continue
        g = rd(f)
        assert list(g.columns) == PPL_COLS, (f, list(g.columns))
        g["_file"] = Path(f).name
        gap_ppl.append(g)
    gap_ppl = pd.concat(gap_ppl, ignore_index=True)

    url_by_host = {}
    for k in comp.index:
        url_by_host.setdefault(host(k), k)

    key_of_person = []
    for _, r in gap_ppl.iterrows():
        k = resolve_key(r["Website Link"], by_host, by_exact)
        key_of_person.append(k)
        if k is None:
            st["people_unmapped"] += 1
    gap_ppl["_key"] = key_of_person
    gap_ppl = gap_ppl[gap_ppl["_key"].notna()].copy()

    existing_rd = {}
    for _, r in ppl.iterrows():
        existing_rd.setdefault(r["Website Link"], r["Root Domain"])
    ppl_rows = ppl.to_dict("records")
    idx = {(r["Website Link"], r["Contact Name"].strip().lower()): i for i, r in enumerate(ppl_rows)}

    for _, r in gap_ppl.iterrows():
        name = r["Contact Name"].strip()
        if blank(name) or name.startswith("http") or "@" in name:
            st["people_bad_name_dropped"] += 1
            continue
        key = r["_key"]
        row = {
            "Company Name": r["Company Name"].strip() or NF,
            "Website Link": key,
            "Root Domain": existing_rd.get(key) or (r["Root Domain"] if not r["Root Domain"].startswith("http")
                                                   else host(r["Root Domain"])),
            "Contact Name": name,
            "Position": r["Position"].strip() or NF,
            "Phone Numbers": r["Phone Numbers"].strip() or NF,
            "Email": NF,
            "LinkedIn Profile": NF,
            "Source Links": clean_sources(r["Source Links"]) or NF,
            "Verification": r["Verification"].strip() or NF,
        }
        em = [e for e in split_list(r["Email"]) if "@" in e]
        row["Email"] = ", ".join(em) if em else NF
        li = r["LinkedIn Profile"].strip()
        if not blank(li):
            if valid_person_li(li):
                row["LinkedIn Profile"] = https_li(li)
            else:
                st["people_bad_linkedin_dropped"] += 1
        if row["Phone Numbers"] != NF and not re.search(r"\d{7,}", digits(row["Phone Numbers"])):
            row["Phone Numbers"] = NF
            st["people_bad_phone_dropped"] += 1
        if row["Source Links"] == NF:
            st["people_without_url_source"] += 1
        k2 = (key, name.lower())
        if k2 in idx:
            old = ppl_rows[idx[k2]]
            for col in ("Phone Numbers", "Email", "LinkedIn Profile", "Source Links", "Verification"):
                if blank(old[col]) and row[col] != NF:
                    old[col] = row[col]
            st["people_deduped"] += 1
        else:
            idx[k2] = len(ppl_rows)
            ppl_rows.append(row)
            st["people_added"] += 1
    merged = {}
    for r in ppl_rows:
        k = (r["Website Link"], r["Contact Name"].strip().lower())
        if k in merged:
            for col in ("Phone Numbers", "Email", "LinkedIn Profile", "Source Links", "Verification"):
                if blank(merged[k][col]) and not blank(r[col]):
                    merged[k][col] = r[col]
            st["people_duplicates_collapsed"] += 1
        else:
            merged[k] = r
    ppl_out = pd.DataFrame(list(merged.values()), columns=PPL_COLS)
    ppl_out["Source Links"] = ppl_out["Source Links"].str.replace(r"\s*\|\s*", "; ", regex=True)

    comp_rows = comp.to_dict("index")
    for k, c in comp_rows.items():
        if host(k) in LINKEDIN_CLEAR and not blank(c["Company LinkedIn"]):
            c["Company LinkedIn"] = NF
            c["Checked Date"] = TODAY
            st["linkedin_cleared"] += 1
    primary_people = {}
    for f in sorted(glob.glob(str(GAP / f"*{GAP_GLOB[market]}*_companies.csv"))):
        if "work" in f:
            continue
        g = rd(f)
        assert list(g.columns) == COMP_COLS[:7], (f, list(g.columns))
        for _, r in g.iterrows():
            key = resolve_key(r["Root Domain"], by_host, by_exact)
            if key is None:
                st["companies_unmapped"] += 1
                continue
            c = comp_rows[key]
            changed = False
            ph = merge_phones(c["Company Phone Numbers"], r["Company Phone Numbers"])
            em = merge_emails(c["Company Emails"], r["Company Emails"])
            if ph != c["Company Phone Numbers"]:
                st["phones_updated"] += 1
                changed = True
            if em != c["Company Emails"]:
                st["emails_updated"] += 1
                changed = True
            c["Company Phone Numbers"], c["Company Emails"] = ph, em
            li_new = r["Company LinkedIn"].strip()
            h = host(key)
            if not blank(li_new) and valid_company_li(li_new):
                if blank(c["Company LinkedIn"]) or h in LINKEDIN_REPLACE:
                    c["Company LinkedIn"] = https_li(li_new)
                    st["linkedin_filled"] += 1
                    changed = True
                elif li_slug(li_new) != li_slug(c["Company LinkedIn"]):
                    st["linkedin_conflict_kept_existing"] += 1
            dm, pos = r["Primary Decision Maker Name"].strip(), r["Position"].strip()
            if not blank(dm) and not dm.startswith("http") and "@" not in dm:
                if blank(c["Primary Decision Maker Name"]):
                    c["Primary Decision Maker Name"] = dm
                    c["Position"] = pos if not blank(pos) else NF
                    st["dm_filled"] += 1
                    changed = True
                    primary_people[key] = dm
                elif c["Primary Decision Maker Name"].strip().lower() != dm.lower():
                    st["dm_conflict_kept_existing"] += 1
            src = urls(r["Sources"])
            if src:
                add = [u for u in src if u not in (c["Sources"] or "")]
                if add:
                    c["Sources"] = "; ".join(([] if blank(c["Sources"]) else [c["Sources"]]) + add)
            if changed:
                c["Checked Date"] = TODAY
                if c["Research Status"] == "not_found":
                    c["Research Status"] = "partial"

    # a filled primary DM must be backed by a people row
    have_names = {(r["Website Link"], norm_name(r["Contact Name"])) for r in ppl_rows}
    for key, dm in primary_people.items():
        if (key, norm_name(dm)) in have_names:
            continue
        sib = [r for r in ppl_rows if host(r["Website Link"]) == host(key) and norm_name(r["Contact Name"]) == norm_name(dm)]
        if sib:
            ppl_rows.append({**sib[0], "Website Link": key})
            st["people_copied_from_sibling_url"] += 1
        else:
            st["primary_dm_without_people_row"] += 1
            report.append(f"{market}: primary DM '{dm}' for {key} has no people row")

    comp_out = pd.DataFrame(list(comp_rows.values()), columns=COMP_COLS)
    comp_out["Sources"] = comp_out["Sources"].str.replace(r"\s*\|\s*", "; ", regex=True)
    comp_out = comp_out.set_index("Root Domain", drop=False).loc[comp.index].reset_index(drop=True)
    for col in comp_out.columns:
        comp_out[col] = comp_out[col].apply(lambda v: v if str(v).strip() else NF)
    for col in ppl_out.columns:
        ppl_out[col] = ppl_out[col].apply(lambda v: v if str(v).strip() else NF)
    assert comp_out["Root Domain"].is_unique and len(comp_out) == len(comp)
    comp_out.to_csv(final / f"{market}_companies.csv", index=False, encoding="utf-8")
    ppl_out.to_csv(final / f"{market}_people.csv", index=False, encoding="utf-8")
    print(market, dict(st), "people rows", len(ppl), "->", len(ppl_out))


if __name__ == "__main__":
    rep = []
    for m in sys.argv[1:] or MARKETS:
        run(m, rep)
    print("\n".join(rep))
