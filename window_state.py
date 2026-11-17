from __future__ import annotations

from collections.abc import Iterable
from typing import TypedDict


class WindowGeometry(TypedDict):
    width: int
    height: int
    x: int
    y: int


MonitorRect = tuple[int, int, int, int]


def parse_window_geometry(value: object) -> WindowGeometry | None:
    """Validate a saved window rectangle before applying it to the GUI."""
    if not isinstance(value, dict):
        return None

    fields = ("width", "height", "x", "y")
    if any(type(value.get(field)) is not int for field in fields):
        return None

    width, height, x, y = (value[field] for field in fields)
    if not 1080 <= width <= 10000 or not 720 <= height <= 10000:
        return None
    if abs(x) > 100000 or abs(y) > 100000:
        return None

    return {"width": width, "height": height, "x": x, "y": y}


def window_geometry_is_visible(
    geometry: WindowGeometry,
    monitors: Iterable[MonitorRect],
    *,
    min_visible_width: int = 160,
    min_visible_height: int = 48,
) -> bool:
    """Return whether enough of the saved window remains on any current monitor."""
    left = geometry["x"]
    top = geometry["y"]
    right = left + geometry["width"]
    bottom = top + geometry["height"]

    for monitor_left, monitor_top, monitor_right, monitor_bottom in monitors:
        if monitor_right <= monitor_left or monitor_bottom <= monitor_top:
            continue
        visible_width = max(0, min(right, monitor_right) - max(left, monitor_left))
        visible_height = max(0, min(bottom, monitor_bottom) - max(top, monitor_top))
        if (
            visible_width >= min(min_visible_width, geometry["width"])
            and visible_height >= min(min_visible_height, geometry["height"])
        ):
            return True
    return False
