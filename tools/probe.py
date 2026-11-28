import re, urllib.request
UA={"User-Agent":"Mozilla/5.0"}
h=urllib.request.urlopen(urllib.request.Request("https://www.whitehouse.gov/gallery/",headers=UA),timeout=25).read().decode()
links=list(dict.fromkeys(re.findall(r'href="(https://www\.whitehouse\.gov/gallery/[^"]+/)"',h)))
print("LINKS",links[:3])
g=urllib.request.urlopen(urllib.request.Request(links[0],headers=UA),timeout=25).read().decode()
print("IMGS",list(dict.fromkeys(re.findall(r'https://www\.whitehouse\.gov/wp-content/uploads/[^"\' )]+',g)))[:12])
print("CREDIT",re.findall(r'(?i)official white house photo[^<]{0,60}',g)[:2])
