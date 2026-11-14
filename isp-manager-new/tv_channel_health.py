"""Compatibility stub: automatic TV channel signal checks are disabled.

The TV catalog, channel URLs and logos remain unchanged. This module intentionally
renders no signal badges and starts no background probes.
"""

def setup(*args, **kwargs):
    return None

def badge(*args, **kwargs):
    return ''

PANEL = ''
