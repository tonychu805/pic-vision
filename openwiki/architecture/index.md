# Files

- [Architecture Overview — tiered detection, three detection eras](overview.md) - The pipeline architecture of pic-vision — the tiered degrade-don't-fail design, the frozen v0 player-geometry baseline, the retired YOLO ball detector, and the primary TrackNet-on-GPU path (RunPod or local RTX 2000 Ada) feeding a backend-agnostic crossing/segment/render/eval spine. Grounded in TECH_SPEC §3/§13 and ADRs 003, 004, 026, 028, 039, 041, 046, 047, 048.
