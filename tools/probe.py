import sys, os, tempfile, io, time
sys.path.insert(0, os.getcwd())
from vok import images
r = images.kremlin("Lavrov")
print("kremlin", len(r), [c["url"][-50:] for c in r[:2]])
d = tempfile.mkdtemp()
for c in r[:2]:
    t = time.time()
    try:
        images.download(c["url"], d + "/k.jpg")
        from PIL import Image; print("SIZE", Image.open(d + "/k.jpg").size, round(time.time() - t, 1), "s")
    except Exception as e:
        print("DL ERR", str(e)[:100])
b = images.best_photo(["Sergei Lavrov"], exclude=set(), workdir=d, person="Sergei Lavrov")
print("BEST Lavrov ->", b and (b["credit"], b["page"][:100]))
