.PHONY: eval test process

eval:
	python3 -m eval.harness --pred rallies.json --labels eval/labels/IMG_7652.jsonl

test:
	python3 -m pytest -q

# RunPod route — cut rally clips from TrackNet predictions.
# Omit NET_Y to calibrate interactively (click the net line); pass NET_Y to reuse a known value.
# Usage: make process VIDEO=game.MOV CSV=predictions.csv OUT=clips/            (interactive net picker)
#        make process VIDEO=game.MOV CSV=predictions.csv NET_Y=210 OUT=clips/   (reuse net_y)
process:
	python3 -m src.cut \
	  --video $(VIDEO) \
	  --predictions $(CSV) \
	  $(if $(NET_Y),--net-y $(NET_Y)) \
	  --out $(OUT)
