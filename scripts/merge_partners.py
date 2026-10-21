#!/usr/bin/env python3
"""Merge raw research CSVs into the six final four-column partner files."""
import csv
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from urllib.parse import urlparse

RAW_DIR = sys.argv[1] if len(sys.argv) > 1 else "/opt/cursor/artifacts/research/raw"
OUT_DIR = sys.argv[2] if len(sys.argv) > 2 else "/opt/cursor/artifacts/deliverables"

CATEGORIES = [
    "Ecommerce Website Development Agencies",
    "Ecommerce Digital Marketing & Performance Agencies",
    "Ecommerce Consulting & Strategy Firms",
    "Ecommerce CRO & UX/UI Agencies",
    "Ecommerce System Integration Companies",
    "Ecommerce Technology & Digital Transformation Firms",
    "Ecommerce SEO Agencies & Consultants",
    "Ecommerce PIM / ERP / Inventory Management Consultants",
    "Ecommerce Product Catalog Management & Data Entry Agencies",
    "Ecommerce Product Photography & Creative Production Agencies",
    "Ecommerce Automation & Workflow Consulting Firms",
    "Ecommerce Product Feed Management Specialists",
    "Fashion Ecommerce Consulting Firms",
    "Fashion Ecommerce Digital Marketing Agencies",
    "Fashion Ecommerce Technology Consultants",
    "Fashion Ecommerce Personalization & Customer Experience Agencies",
    "Fashion Ecommerce CRO & Conversion Optimization Agencies",
    "Fashion Ecommerce Sizing, Fit & Returns Optimization Specialists",
    "Fashion Ecommerce Merchandising & Styling Consultants",
]
FITS = ["Both", "Autommerce OS", "Persona AI"]
COUNTRIES = {
    "Lebanon": "Lebanon",
    "Kuwait": "Kuwait",
    "UAE": "UAE",
    "Qatar": "Qatar",
    "Saudi Arabia": "Saudi_Arabia",
    "United States": "United_States",
}
COUNTRY_ALIASES = {
    "united arab emirates": "UAE", "uae": "UAE", "ksa": "Saudi Arabia",
    "saudi arabia": "Saudi Arabia", "saudi": "Saudi Arabia", "usa": "United States",
    "us": "United States", "united states": "United States", "lebanon": "Lebanon",
    "kuwait": "Kuwait", "qatar": "Qatar",
}


def norm_key(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


CAT_LOOKUP = {norm_key(c): c for c in CATEGORIES}
FIT_LOOKUP = {norm_key(f): f for f in FITS}
FIT_LOOKUP.update({"autommerce": "Autommerce OS", "persona": "Persona AI"})


def canon_url(url):
    url = url.strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    host = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return f"https://{host}" if "." in host else ""


def domain(url):
    return urlparse(url).netloc


def registrable(url):
    parts = domain(url).split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "com", "net", "org", "gov", "edu"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def main():
    rows_by_country = defaultdict(dict)
    rejects = []
    for path in sorted(glob.glob(os.path.join(RAW_DIR, "*.csv"))):
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
                name = row.get("Company Name", "")
                url = canon_url(row.get("Website", ""))
                cat = CAT_LOOKUP.get(norm_key(row.get("Category", "")))
                fit = FIT_LOOKUP.get(norm_key(row.get("Product Fit", "")))
                country = COUNTRY_ALIASES.get(row.get("Country", "").lower())
                problem = None
                if not name:
                    problem = "missing name"
                elif not url:
                    problem = "bad website"
                elif not cat:
                    problem = f"bad category {row.get('Category')!r}"
                elif not fit:
                    problem = f"bad fit {row.get('Product Fit')!r}"
                elif not country:
                    problem = f"bad country {row.get('Country')!r}"
                if problem:
                    rejects.append({"file": os.path.basename(path), "name": name, "problem": problem})
                    continue
                key = registrable(url)
                bucket = rows_by_country[country]
                if key in bucket:
                    existing = bucket[key]
                    if existing["fit"] != fit and "Both" in (existing["fit"], fit):
                        existing["fit"] = "Both"
                    existing["sources"].append(os.path.basename(path))
                    continue
                bucket[key] = {
                    "name": name, "url": url, "cat": cat, "fit": fit,
                    "evidence": row.get("Evidence URL", ""), "note": row.get("Evidence Note", ""),
                    "sources": [os.path.basename(path)],
                }

    os.makedirs(OUT_DIR, exist_ok=True)
    stats = {}
    all_domains = set()
    for country, slug in COUNTRIES.items():
        recs = list(rows_by_country.get(country, {}).values())
        out = os.path.join(OUT_DIR, f"Autommerce_Partners_{slug}.csv")
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["Company Name", "Website", "Category", "Product Fit"])
            for r in recs:
                w.writerow([r["name"], r["url"], r["cat"], r["fit"]])
        ev = os.path.join(OUT_DIR, "evidence", f"Evidence_{slug}.csv")
        os.makedirs(os.path.dirname(ev), exist_ok=True)
        with open(ev, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["Company Name", "Website", "Category", "Product Fit", "Evidence URL", "Evidence Note"])
            for r in recs:
                w.writerow([r["name"], r["url"], r["cat"], r["fit"], r["evidence"], r["note"]])
        fits = Counter(r["fit"] for r in recs)
        stats[country] = {
            "total": len(recs),
            **{f: fits.get(f, 0) for f in FITS},
            "categories": dict(Counter(r["cat"] for r in recs).most_common()),
        }
        all_domains.update(registrable(r["url"]) for r in recs)
    stats["_unique_companies_all_markets"] = len(all_domains)
    stats["_rejected_rows"] = len(rejects)
    with open(os.path.join(OUT_DIR, "evidence", "rejected_rows.json"), "w") as fh:
        json.dump(rejects, fh, indent=1, ensure_ascii=False)
    with open(os.path.join(OUT_DIR, "stats.json"), "w") as fh:
        json.dump(stats, fh, indent=1)
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
