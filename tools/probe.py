import sys, os, tempfile
sys.path.insert(0, os.getcwd())
from vok import images
from PIL import Image
d = tempfile.mkdtemp()
for fn, q in [(images.mehr, "Araghchi"), (images.whitehouse, "Trump"), (images.nasa, "rocket launch")]:
    r = fn(q)
    for c in r[:2]:
        try:
            images.download(c["url"], d + "/x.jpg"); print(fn.__name__, "SIZE", Image.open(d + "/x.jpg").size)
        except Exception as e:
            print(fn.__name__, "DL ERR", str(e)[:80])
