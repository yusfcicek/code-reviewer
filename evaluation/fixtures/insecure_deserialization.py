"""Two deserialisations under one rule, only one of which has a one-line fix.

`yaml.load` becomes `yaml.safe_load`. `pickle.loads` on untrusted input has no
one-line form that is safe, which is why the recipe declines it — and this
fixture is what pins that both are still *reported*.
"""

import pickle

import yaml


def read_config(text: str) -> dict:
    return yaml.load(text)


def read_cache(blob: bytes) -> object:
    return pickle.loads(blob)
