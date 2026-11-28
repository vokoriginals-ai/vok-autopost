import os, tempfile
from vok import images
for fn, q in [(images.kremlin, "Putin"), (images.whitehouse, "Trump"), (images.mehr, "Araghchi"), (images.nasa, "rocket launch")]:
    try:
        r = fn(q)
        print(f"{fn.__name__:10} {q!r}: {len(r)} results")
        for c in r[:2]:
            print("   ", c["credit"], c["url"][:100])
    except Exception as e:
        print(fn.__name__, "ERROR", str(e)[:120])
d = tempfile.mkdtemp()
for qs, person in [(["Vladimir Putin"], "Vladimir Putin"), (["Donald Trump"], "Donald Trump"), (["Abbas Araghchi"], "Abbas Araghchi")]:
    b = images.best_photo(qs, exclude=set(), workdir=d, person=person)
    print("BEST", person, "->", b and (b["credit"], b["page"][:90]))
