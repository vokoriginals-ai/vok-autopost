import sys, os, tempfile, io
sys.path.insert(0, os.getcwd())
from vok import images
r = images.kremlin("Lavrov")
print("kremlin", len(r))
if r:
    import urllib.request; from PIL import Image
    b = urllib.request.urlopen(urllib.request.Request(r[0]["url"], headers={"User-Agent":"Mozilla/5.0"}), timeout=30).read()
    print("SIZE", Image.open(io.BytesIO(b)).size)
d = tempfile.mkdtemp()
b = images.best_photo(["Sergei Lavrov"], exclude=set(), workdir=d, person="Sergei Lavrov")
print("BEST Lavrov ->", b and (b["credit"], b["page"][:100]))
