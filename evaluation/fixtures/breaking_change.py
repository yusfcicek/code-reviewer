"""A public function whose signature changed."""


def render_invoice(order, currency):
    return f"{order}: {currency}"
