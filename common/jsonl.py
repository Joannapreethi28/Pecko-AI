"""Emits contract messages (partial/final/chunk/...) as one JSON object per line
to stdout, per docs/CONTRACT.md. Kept separate from common/log.py (diagnostics,
stderr) so a stage's stdout is a clean, pipeable message stream."""
import json
import sys


def emit(stream=sys.stdout, **fields) -> dict:
    stream.write(json.dumps(fields) + "\n")
    stream.flush()
    return fields
