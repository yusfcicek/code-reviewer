"""Ordinary code with nothing wrong with it."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Money:
    amount: int
    currency: str

    def add(self, other: "Money") -> "Money":
        if other.currency != self.currency:
            raise ValueError("currencies differ")
        return Money(self.amount + other.amount, self.currency)


def total(amounts: list[Money]) -> Money:
    if not amounts:
        raise ValueError("nothing to total")
    result = amounts[0]
    for item in amounts[1:]:
        result = result.add(item)
    return result
