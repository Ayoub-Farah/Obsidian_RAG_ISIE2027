#!/usr/bin/env python3
"""Executable wire-format oracle recreated from specification 1.0 (not RTL)."""
from __future__ import annotations

import argparse
import json
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"\xc3\x5a"
VERSION = 1
TYPES = {"DATA": 1, "REFERENCES": 2, "AGG_CENTRAL": 3,
         "AGG_COLLECT": 4, "AGG_BROADCAST": 5, "SYNC": 0x10,
         "FOLLOW_UP": 0x11, "DELAY_REQ": 0x12, "DELAY_RESP": 0x13,
         "LOCK_ACK": 0x14, "ARM": 0x20, "READY": 0x21}


class FrameError(ValueError):
    pass


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: refin=false, init=FFFF, xorout=0."""
    value = 0xFFFF
    for byte in data:
        value ^= byte << 8
        for _ in range(8):
            value = ((value << 1) ^ (0x1021 if value & 0x8000 else 0)) & 0xFFFF
    return value


def crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def pattern(node: int, cycle: int, count: int, reference: bool = False) -> bytes:
    if count < 0 or not 0 <= cycle < 2**32 or not 0 <= node < 65536:
        raise ValueError("invalid node, cycle or byte count")
    base = 165 + 29 * node + 13 * cycle if reference else 90 + 17 * node + 31 * cycle
    return bytes((base + j) & 255 for j in range(count))


def build_frame(kind: int | str, origin: int, nodes: int, cycle: int, payload: bytes) -> bytes:
    if isinstance(kind, str):
        kind = TYPES[kind]
    if kind not in TYPES.values() or not 0 <= origin < nodes <= 65535:
        raise ValueError("invalid kind, origin or node count")
    if not 0 <= cycle < 2**32 or len(payload) > 65535:
        raise ValueError("invalid cycle or payload length")
    h = MAGIC + struct.pack(">BBHHIH", VERSION, kind, origin, nodes, cycle, len(payload))
    h += struct.pack(">H", crc16(h))
    body = h + payload
    return body + struct.pack("<I", crc32(body))


@dataclass(frozen=True)
class Frame:
    kind: int
    origin: int
    nodes: int
    cycle: int
    payload: bytes


def decode_frame(raw: bytes, *, nodes: int | None = None,
                 cycle: int | None = None, max_frame_bytes: int = 65555) -> Frame:
    if len(raw) < 20 or len(raw) > max_frame_bytes:
        raise FrameError("invalid frame length")
    if raw[:2] != MAGIC or raw[2] != VERSION:
        raise FrameError("invalid magic/version")
    version, kind, origin, n, k, payload_len = struct.unpack(">BBHHIH", raw[2:14])
    if kind not in TYPES.values() or not 0 <= origin < n:
        raise FrameError("invalid kind/origin/node count")
    if len(raw) != 20 + payload_len:
        raise FrameError("payload length mismatch")
    if crc16(raw[:14]) != int.from_bytes(raw[14:16], "big"):
        raise FrameError("header CRC mismatch")
    if crc32(raw[:-4]) != int.from_bytes(raw[-4:], "little"):
        raise FrameError("frame CRC mismatch")
    if nodes is not None and nodes != n:
        raise FrameError("unexpected node count")
    if cycle is not None and cycle != k:
        raise FrameError("unexpected cycle")
    return Frame(kind, origin, n, k, raw[16:-4])


def iter_words(raw: bytes):
    """Yield data, keep, sof, last; byte 0 is data[15:8]."""
    for offset in range(0, len(raw), 2):
        pair = raw[offset:offset + 2]
        yield {"data": int.from_bytes(pair.ljust(2, b"\0"), "big"),
               "keep": 3 if len(pair) == 2 else 2,
               "sof": offset == 0, "last": offset + 2 >= len(raw)}


def reassemble_words(words) -> bytes:
    out = bytearray()
    ended = False
    for number, word in enumerate(words):
        if ended or bool(word["sof"]) != (number == 0):
            raise FrameError("invalid SOF/LAST framing")
        keep = word["keep"]
        if keep not in (2, 3) or (keep == 2 and not word["last"]):
            raise FrameError("invalid KEEP")
        out.extend(int(word["data"]).to_bytes(2, "big")[:2 if keep == 3 else 1])
        ended = bool(word["last"])
    if not ended:
        raise FrameError("missing LAST")
    return bytes(out)


def rewrite_aggregate(raw: bytes, node: int, data_bytes: int, ref_bytes: int,
                      *, broadcast: bool = False) -> bytes:
    """Reference transform with explicit input-error propagation.

    Header validation precedes any relay. The output trailer can only be
    finalized after the incoming trailer has been checked, even for CT RTL.
    """
    if len(raw) < 20 or crc16(raw[:14]) != int.from_bytes(raw[14:16], "big"):
        raise FrameError("invalid header; suppress before relay")
    if raw[:3] != MAGIC + bytes([VERSION]):
        raise FrameError("invalid magic/version")
    kind, origin, n, cycle, length = struct.unpack(">BHHIH", raw[3:14])
    if not 0 <= node < n or len(raw) != length + 20:
        raise FrameError("invalid slot or length")
    bad = crc32(raw[:-4]) != int.from_bytes(raw[-4:], "little")
    body = bytearray(raw[:-4])
    if broadcast:
        if kind != TYPES["AGG_COLLECT"]:
            raise FrameError("only collect can be converted to broadcast")
        body[3] = TYPES["AGG_BROADCAST"]
        body[14:16] = crc16(body[:14]).to_bytes(2, "big")
    elif kind in (TYPES["AGG_COLLECT"], TYPES["AGG_CENTRAL"]):
        expected = n * (data_bytes + (ref_bytes if kind == 3 else 0))
        if length != expected:
            raise FrameError("invalid aggregate length")
        offset = 16 + (n * ref_bytes if kind == 3 else 0) + node * data_bytes
        body[offset:offset + data_bytes] = pattern(node, cycle, data_bytes)
    elif kind != TYPES["AGG_BROADCAST"]:
        raise FrameError("not an aggregate frame")
    result_crc = crc32(body) ^ int(bad)
    return bytes(body) + result_crc.to_bytes(4, "little")


def sample_frames():
    n, d, r, k = 3, 6, 2, 0x01020304
    refs = b"".join(pattern(i, k, r, True) for i in range(n))
    data = b"".join(pattern(i, k, d) for i in range(n))
    slots = pattern(0, k, d) + bytes((n - 1) * d)
    return [
        ("data_even", build_frame("DATA", 1, n, k, pattern(1, k, d))),
        ("data_odd", build_frame("DATA", 2, n, k, pattern(2, k, 5))),
        ("references", build_frame("REFERENCES", 0, n, k, refs)),
        ("aggregate_central_initial", build_frame("AGG_CENTRAL", 0, n, k, refs + slots)),
        ("aggregate_collect_initial", build_frame("AGG_COLLECT", 0, n, k, slots)),
        ("aggregate_broadcast_complete", build_frame("AGG_BROADCAST", 0, n, k, data)),
        ("sync_follow_up", build_frame("FOLLOW_UP", 0, n, k,
          struct.pack(">IQHH", 7, 0x123456789ABCDEF0, 0, 0))),
        ("arm", build_frame("ARM", 0, n, k,
          struct.pack(">IBBHQII", 42, 2, 0, 0, 312500 << 16, k, 6250))),
        ("ready", build_frame("READY", 2, n, k, struct.pack(">IHHII", 42, 1, 0, 0, 0))),
    ]


def write_vectors(path: Path):
    vectors = {"provenance": "Recreated from Rapport_RAG_CT_specification_VHDL.md v1.0; original referenced vectors were not attached.",
               "status": "wire-format reference; not hardware measurements",
               "crc_golden": {"ascii": "123456789", "crc16_hex": "29B1", "crc32_hex": "CBF43926"},
               "vectors": []}
    for name, raw in sample_frames():
        frame = decode_frame(raw)
        vectors["vectors"].append({"name": name, "frame_hex": raw.hex().upper(),
            "frame_bytes": len(raw), "type": frame.kind, "origin_id": frame.origin,
            "node_count": frame.nodes, "cycle_id": frame.cycle,
            "payload_hex": frame.payload.hex().upper(), "words": list(iter_words(raw))})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(vectors, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vectors", type=Path, default=Path(__file__).resolve().parents[1] / "config/vecteurs_trames.json")
    args = parser.parse_args()
    write_vectors(args.vectors)
    print(args.vectors)
