"""Hashing and encryption chosen a decade too late."""

import hashlib


def fingerprint(payload: bytes) -> str:
    return hashlib.md5(payload).hexdigest()


def legacy_digest(payload: bytes) -> str:
    return hashlib.sha1(payload).hexdigest()


def overrides(config: dict) -> dict:
    """`overrides(` ends in `des(`, which the DES pattern once matched."""
    return dict(config)
