"""mc-shot: takes one screenshot of all monitors and sends it to mc-pi (mc-pc.ps1 starts this on request).
Nothing is written to disk. Needs: pip install pillow. Reads url + token from mc-pc.json next to this file."""
import io
import json
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
req = urllib.request.Request(cfg["url"].rstrip("/") + "/api/pc/screenshot", data=buf.getvalue(), method="POST",
                             headers={"Authorization": "Bearer " + cfg["token"], "Content-Type": "image/jpeg"})
with urllib.request.urlopen(req, timeout=20) as r:
    print("sent", r.status, len(buf.getvalue()), "bytes")
