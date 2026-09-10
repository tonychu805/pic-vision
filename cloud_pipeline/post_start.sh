#!/bin/bash
# Run by the base image's own /start.sh (its execute_script "/post_start.sh"
# hook, near the end of its sequence) -- see Dockerfile.selfdriving for why
# this exists instead of a CMD override.
cd /workspace
python3 -u pod_driver.py
