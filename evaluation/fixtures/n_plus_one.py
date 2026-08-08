"""A dictionary lookup in a loop, which is not a database call."""


def summarise(orders, index):
    labels = []
    for order in orders:
        labels.append(index.get(order.id, "unknown"))
    return labels
