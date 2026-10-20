"""Wikidata: companies/brands of Qatar with an official website -> data/raw/wikidata_qa_*.json (skips existing files)."""
import json, os, time
import httpx
RAW = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
Q = {
 "wikidata_qa_companies.json": """SELECT DISTINCT ?item ?itemLabel ?site WHERE {
  { ?item wdt:P17 wd:Q846 } UNION { ?item wdt:P159 ?hq . ?hq wdt:P17 wd:Q846 }
  ?item wdt:P856 ?site . ?item wdt:P31/wdt:P279* ?t .
  VALUES ?t { wd:Q4830453 wd:Q43229 wd:Q431289 wd:Q167037 wd:Q891723 wd:Q6881511 }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,ar". } }""",
 "wikidata_qa_retail.json": """SELECT DISTINCT ?item ?itemLabel ?site WHERE {
  ?item wdt:P856 ?site . { ?item wdt:P17 wd:Q846 } UNION { ?item wdt:P159 ?hq . ?hq wdt:P131* wd:Q846 }
  ?item wdt:P452 ?ind . VALUES ?ind { wd:Q126793 wd:Q1631129 wd:Q484847 wd:Q2166498 wd:Q7406919 wd:Q11634 wd:Q1137109 wd:Q6017969 wd:Q1371849 }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,ar". } }""",
}
H = {"User-Agent": "qatar-ecom-directory-research/1.0 (research bot; python-httpx)", "Accept": "application/sparql-results+json"}
for name, q in Q.items():
    path = os.path.join(RAW, name)
    if os.path.exists(path):
        continue
    for i in range(4):
        try:
            r = httpx.get("https://query.wikidata.org/sparql", params={"query": q}, headers=H, timeout=120)
            b = r.json()["results"]["bindings"]
            json.dump(b, open(path, "w"))
            print(name, len(b))
            break
        except Exception as e:
            print(name, "ERR", type(e).__name__)
            time.sleep(4 * 2 ** i)
