"""Minimal reader for VueScan RAW DNG files (uncompressed 16-bit RGB / RGBI TIFF).

Only what the profiler needs: the largest image IFD, read as a (H, W, C) uint16 array,
plus a few tags for provenance. No demosaicing, no colour management, no dependencies
beyond numpy.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4, 16: 8, 17: 8, 18: 8}
_TYPE_FMT = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d", 13: "I", 16: "Q", 17: "q"}

TAG = dict(
    NewSubfileType=254, ImageWidth=256, ImageLength=257, BitsPerSample=258, Compression=259,
    Photometric=262, Make=271, Model=272, StripOffsets=273, SamplesPerPixel=277, RowsPerStrip=278,
    StripByteCounts=279, XResolution=282, Software=305, SubIFDs=330, UniqueCameraModel=50708,
    BlackLevel=50714, WhiteLevel=50717,
)


@dataclass
class DngMeta:
    width: int
    height: int
    channels: int
    bits: int
    make: str
    model: str
    software: str
    dpi: float | None
    white_level: int


def _parse_ifd(buf: memoryview, off: int, bo: str) -> tuple[dict, int]:
    n = struct.unpack_from(bo + "H", buf, off)[0]
    tags = {}
    p = off + 2
    for _ in range(n):
        tag, typ, cnt = struct.unpack_from(bo + "HHI", buf, p)
        size = _TYPE_SIZE.get(typ, 1) * cnt
        vpos = p + 8 if size <= 4 else struct.unpack_from(bo + "I", buf, p + 8)[0]
        raw = bytes(buf[vpos : vpos + size])
        if typ == 2:
            val = raw.rstrip(b"\x00").decode("latin-1", "replace")
        elif typ in (5, 10):
            f = "II" if typ == 5 else "ii"
            val = tuple(struct.unpack_from(bo + f, raw, 8 * k) for k in range(cnt))
        elif typ in _TYPE_FMT:
            val = struct.unpack_from(bo + _TYPE_FMT[typ] * cnt, raw)
        else:
            val = raw
        tags[tag] = val
        p += 12
    nxt = struct.unpack_from(bo + "I", buf, p)[0]
    return tags, nxt


def read_vuescan_dng(src) -> tuple[np.ndarray, DngMeta]:
    """Read a VueScan DNG from a path, bytes, or file-like object.

    Returns (image[H, W, C] uint16, meta). The image is a view into the file buffer
    when strips are contiguous, so keep memory usage in mind for 23-MP frames (~140 MB).
    """
    if isinstance(src, (bytes, bytearray, memoryview)):
        data = bytes(src)
    elif hasattr(src, "read"):
        data = src.read()
    else:
        with open(src, "rb") as f:
            data = f.read()
    buf = memoryview(data)
    bo = "<" if data[:2] == b"II" else ">"
    if data[2:4] != (b"\x2a\x00" if bo == "<" else b"\x00\x2a"):
        raise ValueError("not a TIFF/DNG file")
    off = struct.unpack_from(bo + "I", buf, 4)[0]
    ifds = []
    while off:
        tags, off = _parse_ifd(buf, off, bo)
        ifds.append(tags)
        for sub in tags.get(TAG["SubIFDs"], ()):
            ifds.append(_parse_ifd(buf, sub, bo)[0])
    main = max(ifds, key=lambda t: t.get(TAG["ImageWidth"], (0,))[0])
    ifd0 = ifds[0]
    w, h = main[TAG["ImageWidth"]][0], main[TAG["ImageLength"]][0]
    spp = main.get(TAG["SamplesPerPixel"], (1,))[0]
    bps = main[TAG["BitsPerSample"]][0]
    if main.get(TAG["Compression"], (1,))[0] != 1:
        raise ValueError("compressed DNG not supported (VueScan RAW should be uncompressed)")
    if bps not in (8, 16):
        raise ValueError(f"unsupported bit depth {bps}")
    offs, cnts = main[TAG["StripOffsets"]], main[TAG["StripByteCounts"]]
    contiguous = all(offs[i] + cnts[i] == offs[i + 1] for i in range(len(offs) - 1))
    dtype = np.dtype(bo + ("u2" if bps == 16 else "u1"))
    if contiguous:
        raw = np.frombuffer(buf, dtype=dtype, count=w * h * spp, offset=offs[0])
    else:
        raw = np.frombuffer(b"".join(bytes(buf[o : o + c]) for o, c in zip(offs, cnts)), dtype=dtype, count=w * h * spp)
    img = raw.reshape(h, w, spp)
    xres = main.get(TAG["XResolution"]) or ifd0.get(TAG["XResolution"])
    dpi = None
    if xres and xres[0][1]:
        dpi = xres[0][0] / xres[0][1]
    white = main.get(TAG["WhiteLevel"], ((1 << bps) - 1,))[0]
    meta = DngMeta(
        width=w, height=h, channels=spp, bits=bps,
        make=ifd0.get(TAG["Make"], ""), model=ifd0.get(TAG["Model"], ""),
        software=ifd0.get(TAG["Software"], ""), dpi=dpi, white_level=int(white),
    )
    return img, meta
