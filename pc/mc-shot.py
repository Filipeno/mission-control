"""mc-shot: takes one screenshot of all monitors and sends it to mc-pi (mc-pc.ps1 starts this on request).
Nothing is written to disk. Needs: pip install pillow. Reads url + token from mc-pc.json next to this file.
  mc-shot.py                      the System tab screenshot
  mc-shot.py --appcard ac-<id>    the screenshot shown with that app card on the phone (stage 11a-1)"""
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageGrab

cfg = json.loads((Path(__file__).resolve().parent / "mc-pc.json").read_text(encoding="utf-8-sig"))
img = ImageGrab.grab(all_screens=True).convert("RGB")
if img.width > 1600:
    img = img.resize((1600, round(img.height * 1600 / img.width)), Image.LANCZOS)
buf = io.BytesIO()
img.save(buf, "JPEG", quality=80)
path = "/api/pc/screenshot"
if sys.argv[1:2] == ["--appcard"]:
    gid = sys.argv[2] if len(sys.argv) > 2 else ""
    if not re.fullmatch(r"ac-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", gid):
        sys.exit("bad app card id")
    path = f"/api/pc/appcard/{gid}/shot"
req = urllib.request.Request(cfg["url"].rstrip("/") + path, data=buf.getvalue(), method="POST",
                             headers={"Authorization": "Bearer " + cfg["token"], "Content-Type": "image/jpeg"})
with urllib.request.urlopen(req, timeout=20) as r:
    print("sent", r.status, len(buf.getvalue()), "bytes")
