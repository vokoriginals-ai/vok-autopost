"""Check which official photo sources the GitHub server can reach."""
import json, re, urllib.request, urllib.parse
UA = {"User-Agent": "Mozilla/5.0 (VOK news bot; contact vok.originals@gmail.com)"}
def get(url, n=400):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25)
        b = r.read()
        return r.status, b
    except Exception as e:
        return str(e)[:80], b""
tests = {
 "kremlin_en_news": "http://en.kremlin.ru/events/president/news",
 "kremlin_search": "http://en.kremlin.ru/search?query=Putin",
 "whitehouse_wp_media": "https://www.whitehouse.gov/wp-json/wp/v2/media?search=Trump&per_page=5",
 "whitehouse_gallery": "https://www.whitehouse.gov/gallery/",
 "nasa_images": "https://images-api.nasa.gov/search?q=launch&media_type=image",
 "tasnim_en": "https://www.tasnimnews.com/en",
 "mehr_en": "https://en.mehrnews.com/",
 "defense_gov": "https://www.defense.gov/Multimedia/Photos/",
 "state_flickr": "https://www.flickr.com/photos/statephotos/",
 "gpo_israel_flickr": "https://www.flickr.com/photos/government_press_office/",
 "ec_audiovisual": "https://audiovisual.ec.europa.eu/en/",
}
for k, u in tests.items():
    s, b = get(u)
    imgs = len(re.findall(rb"\.(?:jpg|jpeg)", b, re.I))
    print(f"{k:22} {s} bytes={len(b)} jpg_refs={imgs}")
    if k == "whitehouse_wp_media" and b:
        try:
            for m in json.loads(b)[:3]:
                print("   ", m.get("source_url","")[:90], "|", re.sub("<[^>]+>","",(m.get("caption") or {}).get("rendered",""))[:90])
        except Exception as e:
            print("   parse", e)
    if k == "kremlin_en_news" and b:
        print("   ", re.findall(rb'https?://static\.kremlin\.ru/media/events/photos/[^"\']+', b)[:3])
