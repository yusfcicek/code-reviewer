"""Three loops deep over a matrix."""


def correlate(rows, columns, depths):
    total = 0
    for row in rows:
        for column in columns:
            for depth in depths:
                total += row * column * depth
    return total
