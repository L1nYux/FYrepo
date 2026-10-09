"""Inference has no total time cap; stalled connections remain bounded."""
import os


def seconds(name, default):
    value = float(os.environ.get(name, default))
    if not 0 <= value <= 86400:
        raise ValueError(name + ' must be between 0 and 86400 seconds')
    return value


CONNECT_SECONDS = seconds('WORKBENCH_INFERENCE_CONNECT_SECONDS', 15) or 15
# A read timeout measures inactivity, not the length of a complete response.
# Explicit 0 disables this too. Catalog/price/quota requests retain their limits.
READ_SECONDS = seconds('WORKBENCH_INFERENCE_IDLE_SECONDS', 900) or None
STREAM_TOTAL_SECONDS = seconds('WORKBENCH_INFERENCE_TOTAL_SECONDS', 0)
ASSISTANT_TOTAL_SECONDS = seconds('WORKBENCH_ASSISTANT_TOTAL_SECONDS', 0)
