.PHONY: eval test

eval:
	python3 -m eval.harness --pred rallies.json --labels eval/labels/dev-set-B.jsonl

test:
	python3 -m pytest -q
