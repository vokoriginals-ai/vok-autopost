import re, urllib.request
UA={"User-Agent":"Mozilla/5.0"}
def get(u): return urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=25).read()
h=get("http://en.kremlin.ru/search?query=Lavrov").decode()
ids=list(dict.fromkeys(re.findall(r'href="/events/president/news/(\d+)"',h)))[:2]
print("IDS",ids)
e=get(f"http://en.kremlin.ru/events/president/news/{ids[0]}/photos").decode()
print("SIZES",sorted(set(re.findall(r"static\.kremlin\.ru/media/events/photos/(\w+)/",e))))
print("SAMPLE",re.findall(r"static\.kremlin\.ru/media/events/photos/\w+/\w+\.jpg",e)[:6])
key=re.findall(r"static\.kremlin\.ru/media/events/photos/\w+/(\w+\.jpg)",e)[0]
for sz in ["small","medium","big","original","large","middle"]:
    try:
        b=get(f"http://static.kremlin.ru/media/events/photos/{sz}/{key}")
        from PIL import Image; import io; im=Image.open(io.BytesIO(b)); print(sz, im.size)
    except Exception as x: print(sz,"ERR",str(x)[:40])
