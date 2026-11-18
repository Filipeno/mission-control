"""mc-shot: takes one screenshot of all monitors and sends it to mc-pi (mc-pc.ps1 starts this on request).
Nothing is written to disk. Needs: pip install pillow. Reads url + token from mc-pc.json next to this file.
  mc-shot.py                      the System tab screenshot
  mc-shot.py --appcard ac-<id>    the screenshot shown with that app card on the phone (stage 11a-1)
  mc-shot.py --gate <id>          the same for any card (approval, question, app card: stage 11e). A locked PC sends
                                  "PC locked" (no picture) instead; the picture is a small JPEG (mc_peek.py)."""
import io
import json
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageGrab

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mc_peek

cfg = json.loads((Path(__file__).resolve().parent / "mc-pc.json").read_text(encoding="utf-8-sig"))
path, headers, locked = "/api/pc/screenshot", {}, False
if sys.argv[1:2] in (["--appcard"], ["--gate"]):
    gid = sys.argv[2] if len(sys.argv) > 2 else ""
    if not mc_peek.CARD_ID.match(gid):
        sys.exit("bad card id")
    path = f"/api/pc/appcard/{gid}/shot"
    locked = mc_peek.is_locked()         # never take a picture of the lock screen / a locked desktop
    if locked:
        headers["X-PC-Locked"] = "1"
if locked:
    body = b""
else:
    img = ImageGrab.grab(all_screens=True).convert("RGB")
    if path != "/api/pc/screenshot":
        body = mc_peek.to_jpeg(img)
    else:
        if img.width > 1600:
            img = img.resize((1600, round(img.height * 1600 / img.width)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80)
        body = buf.getvalue()
req = urllib.request.Request(cfg["url"].rstrip("/") + path, data=body, method="POST",
                             headers={"Authorization": "Bearer " + cfg["token"], "Content-Type": "image/jpeg", **headers})
with urllib.request.urlopen(req, timeout=20) as r:
    print("sent", r.status, len(body), "bytes", "(PC locked)" if locked else "")
