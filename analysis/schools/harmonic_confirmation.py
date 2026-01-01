from typing import Dict, Any


def confirm_harmonic_pattern(
    pattern: Dict[str, Any],
    current_price: float,
) -> Dict[str, Any]:
    """
    Confirms harmonic pattern after break of point C
    """

    points = pattern.get("points")
    if not points:
        return pattern

    point_c = points.get("C")
    direction = pattern.get("direction")

    if point_c is None:
        return pattern

    # =========================
    # Confirmation Logic
    # =========================
    confirmed = False

    if direction == "BUY" and current_price > point_c:
        confirmed = True

    elif direction == "SELL" and current_price < point_c:
        confirmed = True

    if confirmed:
        pattern["status"] = "confirmed"
        pattern["confirmed"] = True
    else:
        pattern["confirmed"] = False

    return pattern
