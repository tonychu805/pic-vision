.PHONY: eval test

eval:
	python3 -m eval.harness --pred rallies.json --labels eval/labels/IMG_7652.jsonl

test:
	python3 -m pytest -q
