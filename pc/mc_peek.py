"""PC peek (stage 11e): the small screenshot sent with an approval / question / app card.
Pure helpers, so they can be tested without a screen: lock check, size capping, and which gates need a picture."""
import io
import re
import subprocess

MAX_WIDTH = 1280
MAX_BYTES = 150 * 1024            # a card screenshot is a small JPEG (the Pi refuses > 300 KB)
CARD_ID = re.compile(r"^(?:ac-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9]{8}-[0-9]{6}-[0-9a-f]{4})$")
PEEK_KINDS = ("appcard", "permission", "question")   # plan cards open in the Docs tab: no screenshot


def is_locked(run=subprocess.run) -> bool:
    """The PC shows the lock screen when the LogonUI process runs (same test mc-pc uses for typing)."""
    try:
        out = run(["tasklist", "/FI", "IMAGENAME eq LogonUI.exe", "/NH"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return False
    return "logonui.exe" in out.lower()


def to_jpeg(img, max_width: int = MAX_WIDTH, max_bytes: int = MAX_BYTES) -> bytes:
    """Shrink a PIL image and re-encode until the JPEG fits max_bytes (quality, then size). Never returns more than the cap
    unless even the smallest try is above it (then the smallest)."""
    img = img.convert("RGB")
    w = min(max_width, img.width)
    data = b""
    for _ in range(6):
        im = img if w == img.width else img.resize((w, max(1, round(img.height * w / img.width))))
        for q in (70, 55, 40):
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=q, optimize=True)
            data = buf.getvalue()
            if len(data) <= max_bytes:
                return data
        w = max(320, int(w * 0.75))
    return data


def gates_needing_shot(gates, done) -> list:
    """Ids of the snapshot's gates that still need a screenshot: right kind, valid id, not sent yet."""
    out = []
    for g in gates or []:
        gid = str(g.get("id", ""))
        if g.get("kind") in PEEK_KINDS and CARD_ID.match(gid) and gid not in done and gid not in out:
            out.append(gid)
    return out
