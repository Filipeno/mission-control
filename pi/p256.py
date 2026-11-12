"""ECDSA P-256 / SHA-256 signature check in plain Python (no wheels needed on the Pi's armv7).

Only verification, with public data, so constant-time code is not needed.
Keys come from Android KeyStore as X.509 SubjectPublicKeyInfo (DER); signatures are DER (r, s).
"""
import hashlib

P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
A = P - 3
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
     0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)
# DER prefix of an uncompressed P-256 SubjectPublicKeyInfo (id-ecPublicKey + prime256v1)
SPKI_PREFIX = bytes.fromhex("3059301306072a8648ce3d020106082a8648ce3d030107034200")


def _add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    if p[0] == q[0] and (p[1] + q[1]) % P == 0:
        return None
    if p == q:
        lam = (3 * p[0] * p[0] + A) * pow(2 * p[1], -1, P) % P
    else:
        lam = (q[1] - p[1]) * pow(q[0] - p[0], -1, P) % P
    x = (lam * lam - p[0] - q[0]) % P
    return x, (lam * (p[0] - x) - p[1]) % P


def _mul(k, p):
    r = None
    while k:
        if k & 1:
            r = _add(r, p)
        p = _add(p, p)
        k >>= 1
    return r


def public_point(spki_der: bytes):
    """(x, y) from an X.509 SubjectPublicKeyInfo; raises ValueError if it is not a valid P-256 key."""
    if len(spki_der) != 91 or not spki_der.startswith(SPKI_PREFIX) or spki_der[26] != 4:
        raise ValueError("not an uncompressed P-256 public key")
    x, y = int.from_bytes(spki_der[27:59], "big"), int.from_bytes(spki_der[59:91], "big")
    if (y * y - (x * x * x + A * x + B)) % P != 0:
        raise ValueError("point not on curve")
    return x, y


def _der_sig(sig: bytes):
    def read_int(b, i):
        if b[i] != 0x02:
            raise ValueError("bad signature")
        n = b[i + 1]
        return int.from_bytes(b[i + 2:i + 2 + n], "big"), i + 2 + n
    if len(sig) < 8 or sig[0] != 0x30 or sig[1] != len(sig) - 2:
        raise ValueError("bad signature")
    r, i = read_int(sig, 2)
    s, i = read_int(sig, i)
    if i != len(sig):
        raise ValueError("bad signature")
    return r, s


def verify(point, message: bytes, sig_der: bytes) -> bool:
    try:
        r, s = _der_sig(sig_der)
    except (ValueError, IndexError):
        return False
    if not (1 <= r < N and 1 <= s < N):
        return False
    e = int.from_bytes(hashlib.sha256(message).digest(), "big")
    w = pow(s, -1, N)
    xy = _add(_mul(e * w % N, G), _mul(r * w % N, point))
    return xy is not None and xy[0] % N == r
