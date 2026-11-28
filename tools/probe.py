import sys, os, tempfile, re
sys.path.insert(0, os.getcwd())
from vok import images
from PIL import Image
d = tempfile.mkdtemp()
r = images.mehr("Araghchi")
m = re.search(r"/d/(\d{4}/\d{2}/\d{2})/\d/(\d+)\.jpg", r[1]["url"])
for dig in "012356":
    u = f"https://media.mehrnews.com/d/{m.group(1)}/{dig}/{m.group(2)}.jpg"
    try:
        images.download(u, d + "/x.jpg"); print("DIGIT", dig, Image.open(d + "/x.jpg").size)
    except Exception as e:
        print("DIGIT", dig, "ERR", str(e)[:50])
