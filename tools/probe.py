import sys, os
sys.path.insert(0, os.getcwd())
from vok import images
r = images.whitehouse("Trump")
print("whitehouse", len(r)); [print("   ", c["url"][:110]) for c in r[:6]]
