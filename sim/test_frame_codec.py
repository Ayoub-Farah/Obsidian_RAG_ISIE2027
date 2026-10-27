import json
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from frame_codec import (FrameError, TYPES, build_frame, crc16, crc32, decode_frame,
                         iter_words, pattern, reassemble_words, rewrite_aggregate, sample_frames)


class WireFormatTests(unittest.TestCase):
    def test_crc_golden(self):
        self.assertEqual(crc16(b"123456789"), 0x29B1)
        self.assertEqual(crc32(b"123456789"), 0xCBF43926)

    def test_header_layout_and_endianness(self):
        raw = build_frame("DATA", 0x123, 0x234, 0xA1B2C3D4, b"abc")
        self.assertEqual(raw[:14].hex(), "c35a010101230234a1b2c3d40003")
        self.assertEqual(raw[14:16], crc16(raw[:14]).to_bytes(2, "big"))
        self.assertEqual(raw[-4:], crc32(raw[:-4]).to_bytes(4, "little"))

    def test_even_and_odd_keep(self):
        for size in (1, 5, 6, 32, 128):
            raw = build_frame("DATA", 1, 3, 7, pattern(1, 7, size))
            words = list(iter_words(raw))
            self.assertEqual(reassemble_words(words), raw)
            self.assertEqual(words[-1]["keep"], 2 if size % 2 else 3)
            self.assertEqual(words[0]["data"], 0xC35A)

    def test_all_vectors_decode(self):
        for _, raw in sample_frames():
            frame = decode_frame(raw, nodes=3, cycle=0x01020304)
            self.assertEqual(len(raw), len(frame.payload) + 20)

    def test_corrupt_header_and_payload_rejected(self):
        raw = build_frame("DATA", 1, 3, 1, pattern(1, 1, 6))
        for pos in (0, 2, 4, 8, 12, 14, 16, len(raw) - 1):
            damaged = bytearray(raw)
            damaged[pos] ^= 1
            with self.assertRaises(FrameError):
                decode_frame(bytes(damaged))

    def test_old_cycle_and_length_rejected(self):
        raw = build_frame("DATA", 1, 3, 1, b"xyz")
        with self.assertRaises(FrameError):
            decode_frame(raw, cycle=2)
        with self.assertRaises(FrameError):
            decode_frame(raw[:-1])
        with self.assertRaises(FrameError):
            decode_frame(raw, max_frame_bytes=len(raw) - 1)

    def test_collect_slots_and_broadcast(self):
        for nodes in (2, 3):
            for size in (5, 6, 32):
                raw = build_frame("AGG_COLLECT", 0, nodes, 19,
                                  pattern(0, 19, size) + bytes((nodes - 1) * size))
                for node in range(1, nodes):
                    raw = rewrite_aggregate(raw, node, size, 2)
                    decode_frame(raw)
                expected = b"".join(pattern(i, 19, size) for i in range(nodes))
                self.assertEqual(decode_frame(raw).payload, expected)
                broadcast = rewrite_aggregate(raw, 0, size, 2, broadcast=True)
                self.assertEqual(decode_frame(broadcast).kind, TYPES["AGG_BROADCAST"])
                self.assertEqual(decode_frame(broadcast).payload, expected)

    def test_central_preserves_individual_references(self):
        nodes, d, r, cycle = 3, 5, 3, 99
        refs = b"".join(pattern(i, cycle, r, True) for i in range(nodes))
        raw = build_frame("AGG_CENTRAL", 0, nodes, cycle,
                          refs + pattern(0, cycle, d) + bytes((nodes - 1) * d))
        for node in range(1, nodes):
            raw = rewrite_aggregate(raw, node, d, r)
        payload = decode_frame(raw).payload
        self.assertEqual(payload[:nodes * r], refs)
        self.assertEqual(payload[nodes * r:], b"".join(pattern(i, cycle, d) for i in range(nodes)))

    def test_aggregate_error_poisoning_survives_multiple_hops(self):
        raw = build_frame("AGG_COLLECT", 0, 3, 0, pattern(0, 0, 6) + bytes(12))
        damaged = bytearray(raw)
        damaged[16] ^= 0x20
        outgoing = rewrite_aggregate(bytes(damaged), 1, 6, 2)
        for node in (2, 1):
            with self.assertRaisesRegex(FrameError, "frame CRC"):
                decode_frame(outgoing)
            self.assertEqual(int.from_bytes(outgoing[-4:], "little") ^ crc32(outgoing[:-4]), 1)
            outgoing = rewrite_aggregate(outgoing, node, 6, 2)
        broadcast = rewrite_aggregate(outgoing, 0, 6, 2, broadcast=True)
        with self.assertRaisesRegex(FrameError, "frame CRC"):
            decode_frame(broadcast)

    def test_invalid_sof_keep_last(self):
        raw = build_frame("DATA", 1, 3, 0, b"abc")
        for change in ("sof", "keep", "last"):
            words = list(iter_words(raw))
            if change == "sof": words[1]["sof"] = True
            elif change == "keep": words[1]["keep"] = 2
            else: words[-1]["last"] = False
            with self.assertRaises(FrameError): reassemble_words(words)

    def test_committed_vectors_match_regeneration(self):
        path = Path(__file__).resolve().parents[1] / "config/vecteurs_trames.json"
        vectors = json.loads(path.read_text())["vectors"]
        self.assertEqual({v["name"]: v["frame_hex"].lower() for v in vectors},
                         {name: raw.hex() for name, raw in sample_frames()})


if __name__ == "__main__":
    unittest.main()
