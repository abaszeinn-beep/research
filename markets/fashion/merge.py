import json
from decide import decide
def load(files):
    d={}
    for f in files:
        try:
            for l in open(f):
                o=json.loads(l)
                if o["ok"] or o["key"] not in d: d[o["key"]]=o
        except FileNotFoundError: pass
    return d
