"""A token generator that uses the wrong generator.

`random` is not weak for every purpose. It is the wrong one for anything a
person must not be able to predict, which is what the rule is about.
"""

import random
import secrets


def session_token() -> str:
    return str(random.random())


def shuffled_order(items: list[str]) -> list[str]:
    random.shuffle(items)
    return items


def safe_token() -> str:
    """The correct form, in the same file, so a rule that fires on both is caught."""
    return secrets.token_hex(16)
