import re, urllib.request
UA = {"User-Agent": "Mozilla/5.0 (VOK news bot)"}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=25).read().decode("utf-8","replace")
h = get("http://en.kremlin.ru/search?query=Putin")
print("KREMLIN SEARCH links:", re.findall(r'href="(/events/president/[^"]+/\d+)"', h)[:5])
print("KREMLIN imgs:", re.findall(r'(?:src|data-src)="([^"]+\.jpg)"', h)[:4])
ev = re.findall(r'href="(/events/president/news/\d+)"', h)
if ev:
    e = get("http://en.kremlin.ru" + ev[0])
    print("EVENT title:", re.findall(r"<title>([^<]+)", e)[:1])
    print("EVENT imgs:", re.findall(r'(https?://static\.kremlin\.ru/media/events/photos/[^"\' ]+)', e)[:4])
    print("EVENT photo links:", re.findall(r'href="(/events/president/news/\d+/photos[^"]*)"', e)[:3])
    print("EVENT license?:", re.findall(r'(?i)creative commons[^<]{0,60}', e)[:1])
w = get("https://www.whitehouse.gov/gallery/")
print("WH gallery links:", re.findall(r'href="(https://www\.whitehouse\.gov/gallery/[^"]+)"', w)[:5])
print("WH imgs:", re.findall(r'(https://www\.whitehouse\.gov/wp-content/uploads/[^"\' ]+\.jpe?g)', w)[:4])
m = get("https://en.mehrnews.com/search?q=Araghchi")
print("MEHR links:", re.findall(r'href="(/news/\d+/[^"]+)"', m)[:4])
print("MEHR imgs:", re.findall(r'(https?://media\.mehrnews\.com/[^"\' ]+\.jpe?g)', m)[:4])
s = get("https://www.flickr.com/search/?text=Rubio&user_id=9364837%40N06")
print("STATE flickr imgs:", re.findall(r'(live\.staticflickr\.com/[^"\' ]+\.jpg)', s)[:4])
