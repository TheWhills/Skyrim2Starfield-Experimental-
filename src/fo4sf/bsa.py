"""Skyrim archives (.bsa): version 104 (Skyrim LE, zlib) and 105 (Skyrim Special Edition, LZ4 frames). Read-only.

Layout (UESP "Skyrim Mod:Archive File Format"; the same reader logic as BSArch / libbsarch):

    header  "BSA\\0", u32 version, u32 header size (36), u32 archive flags, u32 folders, u32 files,
            u32 total folder-name length, u32 total file-name length, u16 file flags, u16 padding
    folders v104: u64 hash, u32 count, u32 offset (16 B);  v105: u64 hash, u32 count, u32 pad, u64 offset (24 B)
    per folder (in folder order): [flag 0x1] u8 length + folder name + NUL, then `count` file records
            u64 hash, u32 size, u32 offset (offset from the start of the archive)
    [flag 0x2] file names: `files` NUL-terminated names in record order
    data    [flag 0x100, "embed names"] u8 length + full path (no NUL); then, when compressed, u32 original size and
            the stream (v104 zlib, v105 an LZ4 frame). A file is compressed when archive flag 0x4 XOR size bit 0x40000000.

Names are looked up as lower-case backslash paths ("meshes\\landscape\\trees\\treepineforest01.nif"); the hashes are not
needed when the archive carries its names (every Bethesda archive does: flags 0x1 and 0x2).
"""
import os
import struct
import zlib

MAGIC = b"BSA\0"
F_DIR_NAMES, F_FILE_NAMES, F_COMPRESSED, F_EMBED_NAMES = 0x1, 0x2, 0x4, 0x100
SIZE_TOGGLE = 0x40000000
SIZE_MASK = 0x3FFFFFFF


class BsaError(ValueError):
    pass


def norm(name: str) -> str:
    return name.replace("/", "\\").lstrip("\\").lower()


def _lz4_decompress(data: bytes, size: int) -> bytes:
    try:
        import lz4.frame
    except ImportError as e:                       # pragma: no cover - environment dependent
        raise BsaError("Skyrim SE archives are LZ4-compressed: pip install lz4") from e
    out = lz4.frame.decompress(data)
    if len(out) != size:
        raise BsaError(f"LZ4 stream gave {len(out)} bytes, expected {size}")
    return out


class Bsa:
    """One archive: `names` (normalised paths), `find(name)` -> index or None, `read(index or name)` -> bytes."""

    def __init__(self, path: str):
        self.path = path
        with open(path, "rb") as f:
            head = f.read(36)
            if len(head) < 36 or head[:4] != MAGIC:
                raise BsaError(f"{path}: not a BSA archive")
            (self.version, hsize, self.flags, nfolders, nfiles, _fl, _nl, self.file_flags) = struct.unpack_from(
                "<IIIIIIIH", head, 4)
            if self.version not in (104, 105):
                raise BsaError(f"{path}: BSA version {self.version} (104 Skyrim LE and 105 Skyrim SE are supported)")
            if not (self.flags & F_DIR_NAMES and self.flags & F_FILE_NAMES):
                raise BsaError(f"{path}: archive without folder/file names is not supported")
            f.seek(hsize)
            rec = 24 if self.version == 105 else 16
            folders = []
            for _ in range(nfolders):
                b = f.read(rec)
                count = struct.unpack_from("<I", b, 8)[0]
                folders.append(count)
            entries = []                           # (folder name, size field, offset)
            for count in folders:
                ln = f.read(1)[0]
                folder = f.read(ln)[:-1].decode("cp1252")
                for _ in range(count):
                    _h, size, off = struct.unpack("<QII", f.read(16))
                    entries.append((folder, size, off))
            names = f.read(_nl).split(b"\0")[:nfiles]
            if len(names) != nfiles:
                raise BsaError(f"{path}: {len(names)} file names for {nfiles} files")
        self.names, self._entries, self._index = [], [], {}
        for (folder, size, off), name in zip(entries, names):
            full = norm(folder + "\\" + name.decode("cp1252"))
            self._index[full] = len(self.names)
            self.names.append(full)
            self._entries.append((size, off))

    def find(self, name: str):
        return self._index.get(norm(name))

    def read(self, which) -> bytes:
        i = self.find(which) if isinstance(which, str) else which
        if i is None:
            raise KeyError(which)
        size, off = self._entries[i]
        compressed = bool(self.flags & F_COMPRESSED) != bool(size & SIZE_TOGGLE)
        size &= SIZE_MASK
        with open(self.path, "rb") as f:
            f.seek(off)
            data = f.read(size)
        if self.flags & F_EMBED_NAMES:
            ln = data[0]
            data = data[1 + ln:]
        if not compressed:
            return data
        raw, = struct.unpack_from("<I", data, 0)
        if self.version == 105:
            return _lz4_decompress(data[4:], raw)
        out = zlib.decompress(data[4:])
        if len(out) != raw:
            raise BsaError(f"zlib stream gave {len(out)} bytes, expected {raw}")
        return out


def build(files: dict, version: int = 105, compress: bool = True, embed_names: bool = False) -> bytes:
    """A small archive from {path: bytes} for synthetic tests (hashes are written as 0; the reader does not use them)."""
    import lz4.frame
    flags = F_DIR_NAMES | F_FILE_NAMES | (F_COMPRESSED if compress else 0) | (F_EMBED_NAMES if embed_names else 0)
    by_folder = {}
    for path, data in sorted(files.items()):
        p = norm(path)
        folder, _, name = p.rpartition("\\")
        by_folder.setdefault(folder, []).append((name, data))
    folders = sorted(by_folder)
    nfiles = sum(len(v) for v in by_folder.values())
    folder_names_len = sum(len(f) + 1 for f in folders)
    file_names = b"".join(n.encode("cp1252") + b"\0" for f in folders for n, _ in by_folder[f])
    rec = 24 if version == 105 else 16
    records_len = sum(1 + len(f) + 1 + 16 * len(by_folder[f]) for f in folders)
    data_start = 36 + rec * len(folders) + records_len + len(file_names)
    blobs, entries, pos = [], [], data_start
    for f in folders:
        for name, data in by_folder[f]:
            body = data
            if compress:
                body = struct.pack("<I", len(data)) + (lz4.frame.compress(data) if version == 105 else zlib.compress(data))
            if embed_names:
                full = (f + "\\" + name).encode("cp1252")
                body = bytes([len(full)]) + full + body
            entries.append((len(body), pos))
            blobs.append(body)
            pos += len(body)
    out = [MAGIC, struct.pack("<IIIIIIIHH", version, 36, flags, len(folders), nfiles, folder_names_len,
                              len(file_names), 0, 0)]
    off = 36 + rec * len(folders)
    for f in folders:
        if version == 105:
            out.append(struct.pack("<QIIQ", 0, len(by_folder[f]), 0, off))
        else:
            out.append(struct.pack("<QII", 0, len(by_folder[f]), off))
        off += 1 + len(f) + 1 + 16 * len(by_folder[f])
    k = 0
    for f in folders:
        out.append(bytes([len(f) + 1]) + f.encode("cp1252") + b"\0")
        for _ in by_folder[f]:
            size, at = entries[k]
            out.append(struct.pack("<QII", 0, size, at))
            k += 1
    out.append(file_names)
    out.extend(blobs)
    return b"".join(out)


class SkyrimArchives:
    """Skyrim's vanilla archives in a Data folder, with the interface pipeline.Converter uses (mesh, texture, material,
    mesh_names). Archives are searched in load order: Skyrim - *.bsa (sorted), then the DLC/Creation Club archives;
    loose files in Data\\meshes / Data\\textures win over archives, as in the game."""

    def __init__(self, data_dir: str, loose: bool = True):
        self.data_dir = data_dir
        self.loose = loose
        names = sorted(os.listdir(data_dir), key=str.lower)
        order = [n for n in names if n.lower().startswith("skyrim - ") and n.lower().endswith(".bsa")]
        order += [n for n in names if n.lower().endswith(".bsa") and n not in order]
        self.archives = [Bsa(os.path.join(data_dir, n)) for n in order]

    def _loose(self, name):
        if not self.loose:
            return None
        p = os.path.join(self.data_dir, *norm(name).split("\\"))
        if os.path.isfile(p):
            with open(p, "rb") as f:
                return f.read()
        return None

    def _read(self, name):
        data = self._loose(name)
        if data is not None:
            return data
        for a in reversed(self.archives):          # a later archive overrides an earlier one
            i = a.find(name)
            if i is not None:
                return a.read(i)
        return None

    def mesh(self, name):
        n = norm(name)
        return self._read(n if n.startswith("meshes\\") else "meshes\\" + n)

    def texture(self, name):
        n = norm(name)
        return self._read(n if n.startswith("textures\\") else "textures\\" + n)

    def material(self, name):                       # Skyrim has no .bgsm materials
        return None

    def mesh_names(self, pattern: str):
        import re
        rx = re.compile(pattern, re.I)
        out = set()
        for a in self.archives:
            out.update(n for n in a.names if n.endswith(".nif") and rx.search(n.replace("\\", "/")))
        return sorted(out)
