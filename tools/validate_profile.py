#!/usr/bin/env python3
"""Reject unrepresentable profiles before IP generation or synthesis."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

MODES = {"RAG_C": 0, "AGG_C": 1, "RAG_D": 2, "AGG_D2": 3, "AGG_D2_PIPE": 4}


def validate(mode, nodes, data_bytes, ref_bytes, max_frame_bytes, *, node_base=0,
             local_nodes=1, period_cycles=6250, header_delay_cycles=10,
             user_clock_hz=62500000, fifo_words=2048):
    errors = []
    if mode not in MODES: errors.append("unknown mode")
    if not 2 <= nodes <= 65535: errors.append("N must be 2..65535")
    if min(data_bytes, ref_bytes, max_frame_bytes, local_nodes, period_cycles, fifo_words) <= 0:
        errors.append("lengths, local population and period must be positive")
    if node_base < 0 or node_base + local_nodes > nodes:
        errors.append("local contiguous node range must be inside 0..N-1")
    if header_delay_cycles < 10:
        errors.append("header delay below the specified validated minimum of 10 cycles")
    if user_clock_hz != 62500000 or period_cycles != 6250:
        errors.append("this profile requires 6250 cycles at 62.5 MHz for 100 us")
    payloads = {"DATA": data_bytes, "REFERENCES": nodes * ref_bytes,
                "AGG_CENTRAL": nodes * (data_bytes + ref_bytes), "AGG_COLLECT": nodes * data_bytes,
                "AGG_BROADCAST": nodes * data_bytes}
    selected = {"RAG_C": ["DATA", "REFERENCES"], "RAG_D": ["DATA"],
                "AGG_C": ["AGG_CENTRAL"], "AGG_D2": ["AGG_COLLECT", "AGG_BROADCAST"],
                "AGG_D2_PIPE": ["AGG_COLLECT", "AGG_BROADCAST"]}.get(mode, [])
    lengths = {name: payloads[name] + 20 for name in selected}
    for name in selected:
        if payloads[name] > 65535: errors.append(f"{name}: payload exceeds uint16; segmentation unsupported")
        if lengths[name] > max_frame_bytes: errors.append(f"{name}: frame exceeds G_MAX_FRAME_BYTES")
        if mode.startswith("AGG") and (lengths[name]+1)//2 > fifo_words//2:
            errors.append(f"{name}: frame exceeds one aggregate ping-pong slot (G_FIFO_WORDS/2 words)")
    return {"mode": mode, "mode_code": MODES.get(mode), "N": nodes, "D": data_bytes,
            "R": ref_bytes, "frame_bytes": lengths, "valid": not errors,
            "errors": errors, "hardware_admission": "not established by static profile validation"}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=MODES, default="RAG_D")
    p.add_argument("--nodes", type=int, default=3)
    p.add_argument("--data-bytes", type=int, default=6)
    p.add_argument("--ref-bytes", type=int, default=2)
    p.add_argument("--max-frame-bytes", type=int, default=4096)
    p.add_argument("--node-base", type=int, default=0)
    p.add_argument("--local-nodes", type=int, default=1)
    p.add_argument("--fifo-words", type=int, default=2048)
    args = p.parse_args()
    result = validate(args.mode, args.nodes, args.data_bytes, args.ref_bytes,
                      args.max_frame_bytes, node_base=args.node_base, local_nodes=args.local_nodes,
                      fifo_words=args.fifo_words)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["valid"] else 1)
