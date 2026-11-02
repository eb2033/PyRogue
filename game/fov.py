"""Field of view (spec §5, stretch goal #6).

Recursive shadowcasting: walls block sight. This replaces the old radius-only
placeholder (which lit everything within range regardless of walls). The
algorithm is the classic 8-octant recursive shadowcasting scan
(Bjorn Bergstrom / RogueBasin), adapted to a [y][x]-indexed grid.
"""

from game.tiles import is_transparent

# Per-octant transforms: (xx, xy, yx, yy) map a local (dx, dy) in "row/col"
# space onto real map deltas around the origin.
_MULT = [
    (1, 0, 0, 1),
    (0, 1, 1, 0),
    (0, -1, 1, 0),
    (-1, 0, 0, 1),
    (-1, 0, 0, -1),
    (0, -1, -1, 0),
    (0, 1, -1, 0),
    (1, 0, 0, -1),
]


def _blocked(game_map, x, y, w, h):
    if x < 0 or x >= w or y < 0 or y >= h:
        return True
    return not is_transparent(game_map, x, y)


def _cast_light(game_map, lit, cx, cy, row, start, end, radius, xx, xy, yx, yy, w, h):
    if start < end:
        return

    radius_squared = radius * radius
    for j in range(row, radius + 1):
        dx, dy = -j - 1, -j
        blocked = False
        new_start = 0.0
        while dx <= 0:
            dx += 1
            mx, my = cx + dx * xx + dy * xy, cy + dx * yx + dy * yy
            l_slope = (dx - 0.5) / (dy + 0.5)
            r_slope = (dx + 0.5) / (dy - 0.5)

            if start < r_slope:
                continue
            if end > l_slope:
                break

            if dx * dx + dy * dy <= radius_squared and 0 <= mx < w and 0 <= my < h:
                lit.add((mx, my))

            wall = _blocked(game_map, mx, my, w, h)
            if blocked:
                if wall:
                    new_start = r_slope
                    continue
                blocked = False
                start = new_start
            else:
                if wall and j < radius:
                    blocked = True
                    _cast_light(
                        game_map,
                        lit,
                        cx,
                        cy,
                        j + 1,
                        start,
                        l_slope,
                        radius,
                        xx,
                        xy,
                        yx,
                        yy,
                        w,
                        h,
                    )
                    new_start = r_slope

        if blocked:
            break


def compute_fov(game_map, visible, x, y, radius):
    """Light `visible` (mutated in place) from (x, y) out to `radius`, and
    return the set of (x, y) cells lit.

    Walls (tiles.is_transparent == False) block sight past them, but the
    blocking wall tile itself is still lit, matching standard shadowcasting
    behavior. Only lit cells are written: `visible` is not cleared first.
    """
    h, w = len(game_map), len(game_map[0])
    lit = {(x, y)}
    for xx, xy, yx, yy in _MULT:
        _cast_light(game_map, lit, x, y, 1, 1.0, 0.0, radius, xx, xy, yx, yy, w, h)
    for tx, ty in lit:
        visible[ty][tx] = True
    return lit


def update_visibility(game_map, visible, seen, x, y, radius=6, previous=None):
    """Recompute `visible` around (x, y) and fold it into `seen`; return the
    set of (x, y) cells now lit.

    Both grids are indexed [y][x] and mutated in place. `previous` is the
    set this function returned last time for the same `visible` grid: only
    those cells are cleared, so a call touches lit cells and nothing else.
    Without it (None) the whole grid is cleared first.
    """
    if previous is None:
        for row in visible:
            row[:] = [False] * len(row)
    else:
        for tx, ty in previous:
            visible[ty][tx] = False

    lit = compute_fov(game_map, visible, x, y, radius)
    for tx, ty in lit:
        seen[ty][tx] = True
    return lit
