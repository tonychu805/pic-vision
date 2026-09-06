.PHONY: eval test process runner

eval:
	python3 -m eval.harness --pred rallies.json --labels eval/labels/IMG_7652.jsonl

test:
	python3 -m pytest -q

# Operator-side job runner (ADR-084): claims jobs the venue desktop apps
# enqueue on the cloud console and runs the pipeline here. Needs
# RUNNER_TOKEN in .env. For an always-on install see
# cloud_pipeline/pic-vision-runner.service.
runner:
	python3 -m cloud_pipeline.job_runner

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
