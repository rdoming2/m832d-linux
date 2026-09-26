"""Minimal CUPS-compatible diagnostics."""
import sys


def info(message):
    print(f'INFO: {message}', file=sys.stderr, flush=True)


def error(message):
    print(f'ERROR: {message}', file=sys.stderr, flush=True)


def state(add=None, remove=None):
    if add:
        print(f'STATE: +{add}', file=sys.stderr, flush=True)
    if remove:
        print(f'STATE: -{remove}', file=sys.stderr, flush=True)
