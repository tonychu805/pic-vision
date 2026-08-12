.PHONY: eval test process

eval:
	python3 -m eval.harness --pred rallies.json --labels eval/labels/IMG_7652.jsonl

test:
	python3 -m pytest -q

# RunPod route — cut rally clips from TrackNet predictions.
# Usage: make process VIDEO=game.MOV CSV=predictions.csv NET_Y=260 OUT=clips/
process:
	python3 scripts/process_footage.py \
	  --video $(VIDEO) \
	  --predictions $(CSV) \
	  --net-y $(NET_Y) \
	  --out $(OUT)
