import sys, os, tempfile
sys.path.insert(0, os.getcwd())
from vok import images
r = images.whitehouse("Trump Rubio")
print("whitehouse", len(r)); [print("   ", c["credit"], c["url"][:100]) for c in r[:4]]
d = tempfile.mkdtemp()
for qs, person in [(["Marco Rubio"], "Marco Rubio"), (["Sergei Lavrov"], "Sergei Lavrov")]:
    b = images.best_photo(qs, exclude=set(), workdir=d, person=person)
    print("BEST", person, "->", b and (b["credit"], b["page"][:100]))
