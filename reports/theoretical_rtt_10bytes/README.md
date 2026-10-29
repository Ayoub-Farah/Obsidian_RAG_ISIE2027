# Theoretical CT and RAG total transmission time

Detailed French report: [Équations théoriques et limitations](rapport_equations_limitations.md).

The curves cover N = 2..30, with 10 bytes of local information per module.
RAG completes a full return to origin: H = N. CT includes collection followed
by redistribution of the completed table, ending at module N.

- CT sends one constant-length aggregate frame with a 10N-byte payload.
- The collection makes N hops back to module 1. Only after the full frame has
  returned does module 1 transmit the completed table again through N-1 hops.
  Redistribution also uses cut-through relays; the table contents stay fixed.
- RAG sends N simultaneous frames, each with a 10-byte payload.
- Both frame types include 32 header bytes and 4 CRC bytes.

These are nominal analytical predictions, not measurements on N physical
boards. The bench contained three physical boards. No FPGA was programmed
and no new hardware measurement was taken to generate these plots.

## Parameters and equations

All times below are nominal. Let P denote payload bytes and let
S(P) = 0.016 * (ceil((P+36)/2) - 1), in microseconds. This measures first
accepted word to last accepted word, so there are W-1 word intervals.

The observed minimum local relay latency is r = 0.288 us. The CT ILA
first-wave loop interval is 2.448 us. Assuming three equivalent links gives
d = (2.448 - 2r)/3 = 0.624 us per effective link. This is an inferred equivalent
parameter including Aurora/PHY/fiber effects, not a separately calibrated
link or optical propagation measurement.

The minimum same-transmitter last-word to next-frame first-word gap observed
in RAG is g = 0.048 us (three cycles). For an ideal homogeneous ring with
synchronous injections, the step between forwarding rounds is modeled as:

    C = max(d + r, S(P_RAG) + g)
    CT_collection(N)     = S(10N) + N*d + (N-1)*r
    CT_redistribution(N) = S(10N) + (N-1)*d + (N-2)*r
    Total_CT(N)         = CT_collection + delta + CT_redistribution
    Total_RAG(N)        = S(10) + d + (N-1)*C

CT therefore counts two serialization spans, 2N-1 link traversals, and 2N-3
intermediate cut-through relays. Module 1 must receive the complete frame
before the second transmission begins. Its reinjection/processing delay delta
is not identified by the hardware captures: the nominal plot assumes delta=0.
Use `--ct-redistribution-delay-ns` to supply another explicit assumption.
The new redistribution phase itself has not been measured on hardware.

At P_RAG=10 bytes, S=0.352 us, the transmitter service term is 0.400 us,
and the wave term d+r=0.912 us dominates. The ideal symmetric model therefore
does not introduce an additional transmitter queue at this payload size.
For the selected parameters the formulas simplify to:

    Total_CT(N)  = 1.984*N - 0.944 us     (delta = 0)
    Total_RAG(N) = 0.912*N + 0.064 us

At N=30 the theoretical totals are CT=58.576 us and RAG=27.424 us.

As a consistency check of the service-time model, P_RAG=257 and H=3 predict
7.728 us, compared with 7.728..7.840 us in the existing three-board captures.
This is not validation of the extrapolation to other module counts.

Additional clock-compensation pauses, heterogeneous links, jitter and unrelated
traffic are excluded. Their effects and general N-injector queueing are not
fully identified by the existing tests. The curves do not assert a worst-case
bound or a confidence interval. Serialization overlaps across cut-through hops.

## Files and reproduction

- `rtt_vs_modules.png`, `.pdf`, `.svg`: updated English figure; the historical
  filenames are retained, but the ordinate is now total transmission time.
- `rtt_vs_modules.csv`: all 29 theoretical data points, explicitly labeled.
- `model_assumptions.json`: coefficients, assumptions and source hashes.

From the project root:

```powershell
py -3 scripts/plot_theoretical_rtt.py --local-bytes 10 --min-modules 2 --max-modules 30
```
