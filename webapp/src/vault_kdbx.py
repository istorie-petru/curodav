"""Reads and writes KeePass 2 files, version 4 (KDBX 4), the format of the Accounts vault (features/accounts-vault.md).

`load` decrypts a file into a `Database`: the XML tree with protected values kept sealed in memory (`value_text` opens one),
plus the binary attachments. `dump` encrypts a `Database` back into a file with a fresh master seed, IV, KDF salt and inner stream key.
`new_database` makes an empty one. Keys come from `composite_key`: a password, a key file, or both.

Supported on reading: ChaCha20 and AES-256 bodies, gzip or none, Argon2id and AES-KDF. Argon2d files (the KeePassXC default)
cannot be opened, because no Argon2d is installed; the error says how to switch the file to Argon2id. Written files use
ChaCha20, gzip and Argon2id, which KeePassXC, KeePassDX and Strongbox all open.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import os
import struct
import uuid as uuidlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

SIG1, SIG2 = 0x9AA2D903, 0xB54BFB67
CIPHER_AES256 = bytes.fromhex("31c1f2e6bf714350be5805216afc5aff")
CIPHER_CHACHA20 = bytes.fromhex("d6038a2b8b6f4cb5a524339a31dbb59a")
KDF_AES = bytes.fromhex("c9d9f39a628a4460bf740d08c18a4fea")
KDF_ARGON2D = bytes.fromhex("ef636ddf8c29444b91f7a9a403e30a0c")
KDF_ARGON2ID = bytes.fromhex("9e298b1956db4773b23dfc3ec6f0a1e6")
INNER_CHACHA20 = 3
BLOCK_SIZE = 1024 * 1024
# Written files: about half a second of Argon2id on a desktop, more on a small server.
DEFAULT_KDF = {"iterations": 25, "memory": 64 * 1024 * 1024, "parallelism": 2}
_EPOCH = datetime(1, 1, 1, tzinfo=timezone.utc)


class VaultError(Exception):
    """A file that is not a KDBX 4 vault, or one this module cannot open."""


class WrongKey(VaultError):
    """The password or key file does not open the vault."""


@dataclass
class Database:
    root: ET.Element
    binaries: list[tuple[int, bytes]] = field(default_factory=list)  # (flags, data), referenced by index from entries
    kdf: dict = field(default_factory=lambda: dict(DEFAULT_KDF))


# ---------------------------------------------------------------- keys

def key_file_key(data: bytes) -> bytes:
    """The 32-byte key a key file contributes, in the ways KeePass reads them: XML v1 or v2, 32 raw bytes, 64 hex, else a hash."""
    text = data.strip()
    if text.startswith(b"<?xml") or text.startswith(b"<KeyFile"):
        try:
            tree = ET.fromstring(text)
            node = tree.find("./Key/Data")
            version = (tree.findtext("./Meta/Version") or "1.0").strip()
            if node is not None and node.text:
                if version.startswith("2"):
                    return bytes.fromhex("".join(node.text.split()))
                return base64.b64decode(node.text.strip())
        except (ET.ParseError, ValueError):
            pass
    if len(data) == 32:
        return data
    if len(text) == 64:
        try:
            return bytes.fromhex(text.decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            pass
    return hashlib.sha256(data).digest()


def composite_key(password: str | None, key_file: bytes | None = None) -> bytes:
    parts = b""
    if password:
        parts += hashlib.sha256(password.encode("utf-8")).digest()
    if key_file:
        parts += key_file_key(key_file)
    if not parts:
        raise VaultError("A vault needs a password, a key file or both")
    return hashlib.sha256(parts).digest()


def make_key_file() -> bytes:
    """A new KeePass XML key file (version 2.0) holding 32 random bytes."""
    key = os.urandom(32)
    digest = hashlib.sha256(key).hexdigest()[:8].upper()
    hexkey = key.hex().upper()
    groups = " ".join(hexkey[i:i + 8] for i in range(0, 64, 8))
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<KeyFile>\n\t<Meta>\n\t\t<Version>2.0</Version>\n\t</Meta>\n\t<Key>\n'
            f'\t\t<Data Hash="{digest}">{groups}</Data>\n\t</Key>\n</KeyFile>\n').encode("utf-8")


# ---------------------------------------------------------------- variant dictionary

_VD_TYPES = {0x04: "<I", 0x05: "<Q", 0x08: "?", 0x0C: "<i", 0x0D: "<q"}


def _read_vd(data: bytes) -> dict:
    out, pos = {}, 2
    while pos < len(data):
        kind = data[pos]
        pos += 1
        if kind == 0:
            break
        (klen,) = struct.unpack_from("<i", data, pos)
        pos += 4
        key = data[pos:pos + klen].decode("utf-8")
        pos += klen
        (vlen,) = struct.unpack_from("<i", data, pos)
        pos += 4
        raw = data[pos:pos + vlen]
        pos += vlen
        if kind in _VD_TYPES:
            out[key] = struct.unpack(_VD_TYPES[kind], raw)[0]
        elif kind == 0x18:
            out[key] = raw.decode("utf-8")
        else:
            out[key] = raw
    return out


def _write_vd(items: list[tuple[int, str, object]]) -> bytes:
    out = b"\x00\x01"
    for kind, key, value in items:
        raw = struct.pack(_VD_TYPES[kind], value) if kind in _VD_TYPES else value
        k = key.encode("utf-8")
        out += bytes([kind]) + struct.pack("<i", len(k)) + k + struct.pack("<i", len(raw)) + raw
    return out + b"\x00"


# ---------------------------------------------------------------- KDF

def _transform(params: dict, composite: bytes) -> bytes:
    kdf = params.get("$UUID")
    if kdf == KDF_ARGON2ID:
        if params.get("K") or params.get("A"):
            raise VaultError("This vault uses Argon2 secret or associated data, which is not supported")
        return Argon2id(salt=params["S"], length=32, iterations=int(params["I"]), lanes=int(params["P"]),
                        memory_cost=int(params["M"]) // 1024).derive(composite)
    if kdf == KDF_AES:
        cipher = Cipher(algorithms.AES(params["S"]), modes.ECB()).encryptor()
        block = composite
        for _ in range(int(params["R"])):
            block = cipher.update(block)
        return hashlib.sha256(block).digest()
    if kdf == KDF_ARGON2D:
        raise VaultError("This vault uses Argon2d. In KeePassXC, open Database Security, Encryption Settings, choose Argon2id, "
                         "save, and import it again")
    raise VaultError("This vault uses a key derivation this app does not know")


def _block_key(base: bytes, index: int) -> bytes:
    return hashlib.sha512(struct.pack("<Q", index) + base).digest()


# ---------------------------------------------------------------- values kept sealed in memory

# Protected values (passwords, secret fields) are held in the open vault encrypted under a key made when the process
# started, and opened only for the moment one is read. A copy of the memory of a running server then shows no password
# in the clear, though anyone who can read this process's memory can also read the key: it is a layer, not a wall.
_AEAD = ChaCha20Poly1305(os.urandom(32))


def seal_bytes(data: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + _AEAD.encrypt(nonce, data, None)


def unseal_bytes(blob: bytes) -> bytes:
    return _AEAD.decrypt(blob[:12], blob[12:], None)


def seal_value(el: ET.Element) -> None:
    el.text = base64.b64encode(seal_bytes((el.text or "").encode("utf-8"))).decode()
    el.set("Sealed", "1")


def value_text(el: ET.Element | None) -> str:
    """The text of a Value element, opened if it is sealed."""
    if el is None:
        return ""
    if el.get("Sealed") == "1":
        return unseal_bytes(base64.b64decode(el.text or "")).decode("utf-8")
    return el.text or ""


def set_value(el: ET.Element, text: str, protected: bool) -> None:
    el.text = text
    el.attrib.pop("Sealed", None)
    if protected:
        el.set("Protected", "True")
        seal_value(el)
    else:
        el.attrib.pop("Protected", None)


# ---------------------------------------------------------------- inner stream and protected values

class _Stream:
    def __init__(self, key: bytes):
        h = hashlib.sha512(key).digest()
        self._enc = Cipher(algorithms.ChaCha20(h[:32], b"\x00" * 4 + h[32:44]), mode=None).encryptor()

    def xor(self, data: bytes) -> bytes:
        return self._enc.update(data)


def _protected_values(root: ET.Element):
    return [el for el in root.iter("Value") if el.get("Protected", "").lower() == "true"]


# ---------------------------------------------------------------- times

def encode_time(when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    return base64.b64encode(struct.pack("<q", int((when - _EPOCH).total_seconds()))).decode()


def decode_time(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        if len(text) == 12 and text.endswith("="):
            return _EPOCH + timedelta(seconds=struct.unpack("<q", base64.b64decode(text))[0])
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, struct.error, OverflowError):
        return None


def new_uuid() -> str:
    return base64.b64encode(uuidlib.uuid4().bytes).decode()


# ---------------------------------------------------------------- load

def load(data: bytes, composite: bytes) -> Database:
    """Opens a vault with the composite key (`composite_key`). A file that is damaged or cut short ends as a VaultError."""
    try:
        return _load(data, composite)
    except VaultError:
        raise
    except (struct.error, IndexError, KeyError, ValueError, TypeError, OverflowError, EOFError, OSError, ET.ParseError, MemoryError):
        raise VaultError("The file is damaged") from None
    except Exception as exc:  # the crypto library's own errors (a bad tag, a bad padding)
        if type(exc).__module__.startswith("cryptography"):
            raise VaultError("The file is damaged") from None
        raise


def _load(data: bytes, composite: bytes) -> Database:
    if len(data) < 12:
        raise VaultError("This is not a KeePass file")
    s1, s2, minor, major = struct.unpack_from("<IIHH", data, 0)
    if (s1, s2) != (SIG1, SIG2):
        raise VaultError("This is not a KeePass file")
    if major == 3:
        return _load_v3(data, composite)
    if major != 4:
        raise VaultError("Only KeePass 2 files (KDBX 3.1 and 4) can be opened")
    pos, header = 12, {}
    while True:
        if pos + 5 > len(data):
            raise VaultError("The file is cut short")
        fid = data[pos]
        (size,) = struct.unpack_from("<I", data, pos + 1)
        header[fid] = data[pos + 5:pos + 5 + size]
        pos += 5 + size
        if fid == 0:
            break
    head = data[:pos]
    if hashlib.sha256(head).digest() != data[pos:pos + 32]:
        raise VaultError("The file is damaged")
    kdf_params = _read_vd(header[11])
    transformed = _transform(kdf_params, composite)
    seed = header[4]
    enc_key = hashlib.sha256(seed + transformed).digest()
    hmac_base = hashlib.sha512(seed + transformed + b"\x01").digest()
    if not hmac.compare_digest(hmac.new(_block_key(hmac_base, 0xFFFFFFFFFFFFFFFF), head, hashlib.sha256).digest(), data[pos + 32:pos + 64]):
        raise WrongKey("The password or key file is wrong")
    pos += 64
    body, index = b"", 0
    while True:
        mac = data[pos:pos + 32]
        (size,) = struct.unpack_from("<i", data, pos + 32)
        chunk = data[pos + 36:pos + 36 + size]
        check = hmac.new(_block_key(hmac_base, index), struct.pack("<Q", index) + struct.pack("<i", size) + chunk, hashlib.sha256).digest()
        if not hmac.compare_digest(check, mac):
            raise VaultError("The file is damaged")
        pos += 36 + size
        index += 1
        if size == 0:
            break
        body += chunk
    cipher, iv = header[2], header[7]
    if cipher == CIPHER_CHACHA20:
        plain = Cipher(algorithms.ChaCha20(enc_key, b"\x00" * 4 + iv), mode=None).decryptor().update(body)
    elif cipher == CIPHER_AES256:
        raw = Cipher(algorithms.AES(enc_key), modes.CBC(iv)).decryptor()
        unpad = padding.PKCS7(128).unpadder()
        plain = unpad.update(raw.update(body) + raw.finalize()) + unpad.finalize()
    else:
        raise VaultError("This vault uses a cipher this app does not know")
    if struct.unpack("<I", header[3])[0] == 1:
        plain = gzip.decompress(plain)
    pos, stream_key, binaries = 0, b"", []
    while True:
        fid = plain[pos]
        (size,) = struct.unpack_from("<i", plain, pos + 1)
        value = plain[pos + 5:pos + 5 + size]
        pos += 5 + size
        if fid == 0:
            break
        if fid == 1 and struct.unpack("<I", value)[0] != INNER_CHACHA20:
            raise VaultError("This vault protects its values with a stream this app does not know")
        if fid == 2:
            stream_key = value
        if fid == 3:
            binaries.append((value[0], value[1:]))
    root = ET.fromstring(plain[pos:])
    stream = _Stream(stream_key)
    for el in _protected_values(root):
        el.text = stream.xor(base64.b64decode(el.text or "")).decode("utf-8", "replace")
        seal_value(el)
    kdf = {"iterations": int(kdf_params.get("I", DEFAULT_KDF["iterations"])), "memory": int(kdf_params.get("M", DEFAULT_KDF["memory"])),
           "parallelism": int(kdf_params.get("P", DEFAULT_KDF["parallelism"]))}
    return Database(root=root, binaries=binaries, kdf=kdf)


# ---------------------------------------------------------------- KDBX 3.1, read only (for imports)

def _salsa20_stream(key: bytes, nonce: bytes):
    """Salsa20/20 keystream; KDBX 3.1 protects values with it and the installed library has no Salsa20."""
    def rotl(v, c):
        return ((v << c) & 0xFFFFFFFF) | (v >> (32 - c))

    const = struct.unpack("<4I", b"expand 32-byte k")
    k = struct.unpack("<8I", key)
    n = struct.unpack("<2I", nonce)
    counter = 0
    while True:
        x = [const[0], k[0], k[1], k[2], k[3], const[1], n[0], n[1], counter & 0xFFFFFFFF, counter >> 32, const[2], k[4], k[5], k[6], k[7], const[3]]
        w = list(x)
        for _ in range(10):
            for a, b, c, d in ((0, 4, 8, 12), (5, 9, 13, 1), (10, 14, 2, 6), (15, 3, 7, 11)):
                w[b] ^= rotl((w[a] + w[d]) & 0xFFFFFFFF, 7); w[c] ^= rotl((w[b] + w[a]) & 0xFFFFFFFF, 9)
                w[d] ^= rotl((w[c] + w[b]) & 0xFFFFFFFF, 13); w[a] ^= rotl((w[d] + w[c]) & 0xFFFFFFFF, 18)
            for a, b, c, d in ((0, 1, 2, 3), (5, 6, 7, 4), (10, 11, 8, 9), (15, 12, 13, 14)):
                w[b] ^= rotl((w[a] + w[d]) & 0xFFFFFFFF, 7); w[c] ^= rotl((w[b] + w[a]) & 0xFFFFFFFF, 9)
                w[d] ^= rotl((w[c] + w[b]) & 0xFFFFFFFF, 13); w[a] ^= rotl((w[d] + w[c]) & 0xFFFFFFFF, 18)
        yield from struct.pack("<16I", *((w[i] + x[i]) & 0xFFFFFFFF for i in range(16)))
        counter += 1


def _load_v3(data: bytes, composite: bytes) -> Database:
    pos, header = 12, {}
    while True:
        fid = data[pos]
        (size,) = struct.unpack_from("<H", data, pos + 1)
        header[fid] = data[pos + 3:pos + 3 + size]
        pos += 3 + size
        if fid == 0:
            break
    transformed = _transform({"$UUID": KDF_AES, "S": header[5], "R": struct.unpack("<Q", header[6])[0]}, composite)
    key = hashlib.sha256(header[4] + transformed).digest()
    if header[2] != CIPHER_AES256:
        raise VaultError("This KDBX 3.1 file uses a cipher this app does not know")
    raw = Cipher(algorithms.AES(key), modes.CBC(header[7])).decryptor()
    try:
        unpad = padding.PKCS7(128).unpadder()
        plain = unpad.update(raw.update(data[pos:]) + raw.finalize()) + unpad.finalize()
    except ValueError:
        raise WrongKey("The password or key file is wrong") from None
    if plain[:32] != header[9]:
        raise WrongKey("The password or key file is wrong")
    pos, body = 32, b""
    while True:
        (size,) = struct.unpack_from("<i", plain, pos + 36)
        chunk = plain[pos + 40:pos + 40 + size]
        if size and hashlib.sha256(chunk).digest() != plain[pos + 4:pos + 36]:
            raise VaultError("The file is damaged")
        pos += 40 + size
        if size == 0:
            break
        body += chunk
    if struct.unpack("<I", header[3])[0] == 1:
        body = gzip.decompress(body)
    root = ET.fromstring(body)
    stream_id = struct.unpack("<I", header[10])[0]
    if stream_id == 2:
        keystream = _salsa20_stream(hashlib.sha256(header[8]).digest(), bytes.fromhex("E830094B97205D2A"))
        xor = lambda b: bytes(c ^ next(keystream) for c in b)  # noqa: E731
    elif stream_id == INNER_CHACHA20:
        xor = _Stream(header[8]).xor
    else:
        raise VaultError("This vault protects its values with a stream this app does not know")
    for el in _protected_values(root):
        el.text = xor(base64.b64decode(el.text or "")).decode("utf-8", "replace")
        seal_value(el)
    return Database(root=root)


# ---------------------------------------------------------------- dump

def dump(db: Database, composite: bytes) -> bytes:
    seed, iv, salt, stream_key = os.urandom(32), os.urandom(12), os.urandom(32), os.urandom(64)
    kdf = _write_vd([(0x42, "$UUID", KDF_ARGON2ID), (0x42, "S", salt), (0x04, "P", db.kdf["parallelism"]),
                     (0x05, "M", db.kdf["memory"]), (0x05, "I", db.kdf["iterations"]), (0x04, "V", 0x13)])
    fields = [(2, CIPHER_CHACHA20), (3, struct.pack("<I", 1)), (4, seed), (7, iv), (11, kdf), (0, b"\r\n\r\n")]
    head = struct.pack("<IIHH", SIG1, SIG2, 0, 4) + b"".join(bytes([f]) + struct.pack("<I", len(v)) + v for f, v in fields)
    transformed = Argon2id(salt=salt, length=32, iterations=db.kdf["iterations"], lanes=db.kdf["parallelism"],
                           memory_cost=db.kdf["memory"] // 1024).derive(composite)
    enc_key = hashlib.sha256(seed + transformed).digest()
    hmac_base = hashlib.sha512(seed + transformed + b"\x01").digest()

    root = ET.fromstring(ET.tostring(db.root))  # a copy, so the open vault keeps its sealed values
    stream = _Stream(stream_key)
    for el in _protected_values(root):
        plain = value_text(el)
        el.attrib.pop("Sealed", None)
        el.text = base64.b64encode(stream.xor(plain.encode("utf-8"))).decode()
    inner = bytes([1]) + struct.pack("<i", 4) + struct.pack("<I", INNER_CHACHA20)
    inner += bytes([2]) + struct.pack("<i", len(stream_key)) + stream_key
    for flags, blob in db.binaries:
        inner += bytes([3]) + struct.pack("<i", len(blob) + 1) + bytes([flags]) + blob
    inner += bytes([0]) + struct.pack("<i", 0)
    xml = b'<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n' + ET.tostring(root, encoding="utf-8")
    body = Cipher(algorithms.ChaCha20(enc_key, b"\x00" * 4 + iv), mode=None).encryptor().update(gzip.compress(inner + xml))

    out = head + hashlib.sha256(head).digest() + hmac.new(_block_key(hmac_base, 0xFFFFFFFFFFFFFFFF), head, hashlib.sha256).digest()
    chunks = [body[i:i + BLOCK_SIZE] for i in range(0, len(body), BLOCK_SIZE)] + [b""]
    for index, chunk in enumerate(chunks):
        size = struct.pack("<i", len(chunk))
        out += hmac.new(_block_key(hmac_base, index), struct.pack("<Q", index) + size + chunk, hashlib.sha256).digest() + size + chunk
    return out


# ---------------------------------------------------------------- new

def _times() -> ET.Element:
    times = ET.Element("Times")
    now = encode_time()
    for tag, value in (("CreationTime", now), ("LastModificationTime", now), ("LastAccessTime", now), ("ExpiryTime", now),
                       ("Expires", "False"), ("UsageCount", "0"), ("LocationChanged", now)):
        ET.SubElement(times, tag).text = value
    return times


def new_group(name: str, icon: int = 48) -> ET.Element:
    group = ET.Element("Group")
    ET.SubElement(group, "UUID").text = new_uuid()
    ET.SubElement(group, "Name").text = name
    ET.SubElement(group, "Notes").text = ""
    ET.SubElement(group, "IconID").text = str(icon)
    group.append(_times())
    ET.SubElement(group, "IsExpanded").text = "True"
    return group


def new_times() -> ET.Element:
    return _times()


def new_database(name: str = "Accounts") -> Database:
    root = ET.Element("KeePassFile")
    meta = ET.SubElement(root, "Meta")
    for tag, value in (("Generator", "Curodav"), ("DatabaseName", name), ("DatabaseNameChanged", encode_time()), ("DefaultUserName", ""),
                       ("MaintenanceHistoryDays", "365"), ("RecycleBinEnabled", "True"), ("HistoryMaxItems", "10"),
                       ("HistoryMaxSize", "6291456")):
        ET.SubElement(meta, tag).text = value
    protection = ET.SubElement(meta, "MemoryProtection")
    for tag, value in (("ProtectTitle", "False"), ("ProtectUserName", "False"), ("ProtectPassword", "True"), ("ProtectURL", "False"),
                       ("ProtectNotes", "False")):
        ET.SubElement(protection, tag).text = value
    body = ET.SubElement(root, "Root")
    body.append(new_group(name))
    ET.SubElement(body, "DeletedObjects")
    return Database(root=root)
