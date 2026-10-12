# Mini Roguelike in Python — Offline Reference

Everything here uses only Python's standard library (`curses` + `random`), so it works with zero internet and zero installs. `curses` ships with Python on macOS/Linux. On Windows you'd need `windows-curses`, so if you're on Windows, grab that before you lose signal (`pip install windows-curses`).

---

## 1. Curses Basics

```python
import curses

def main(stdscr):
    curses.curs_set(0)          # hide cursor
    stdscr.nodelay(False)       # wait for input (True = non-blocking)
    stdscr.clear()

    height, width = stdscr.getmaxyx()

    while True:
        stdscr.clear()
        stdscr.addstr(0, 0, "Hello, roguelike!")
        stdscr.refresh()

        key = stdscr.getch()    # blocks until keypress
        if key == ord('q'):
            break

curses.wrapper(main)   # handles setup/teardown safely, even on crash
```

Key points:
- `curses.wrapper(main)` is the standard entry point — it restores your terminal even if your code crashes.
- `stdscr.addstr(y, x, text)` — note it's **row, then column**.
- `stdscr.getch()` returns an int; compare with `ord('w')` or constants like `curses.KEY_UP`.
- `stdscr.refresh()` must be called to actually draw changes.

### Colors
```python
curses.start_color()
curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
stdscr.addstr(y, x, "@", curses.color_pair(1))
```

### Common keys
```python
curses.KEY_UP, curses.KEY_DOWN, curses.KEY_LEFT, curses.KEY_RIGHT
# or just use WASD via ord('w'), ord('a'), ord('s'), ord('d')
```

---

## 2. Map Representation

Simplest approach: a 2D list of characters or ints.

```python
MAP_WIDTH, MAP_HEIGHT = 40, 20

def make_empty_map(w, h, fill='#'):
    return [[fill for _ in range(w)] for _ in range(h)]

game_map = make_empty_map(MAP_WIDTH, MAP_HEIGHT)
```

Common tile chars: `#` wall, `.` floor, `+` door, `>` stairs down, `@` player.

Rendering:
```python
def draw_map(stdscr, game_map):
    for y, row in enumerate(game_map):
        stdscr.addstr(y, 0, ''.join(row))
```

---

## 3. Random Dungeon Generation (Rooms + Corridors)

Classic approach: carve random rectangular rooms, connect their centers with corridors.

```python
import random

class Rect:
    def __init__(self, x, y, w, h):
        self.x1, self.y1 = x, y
        self.x2, self.y2 = x + w, y + h

    def center(self):
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)

    def intersects(self, other):
        return (self.x1 <= other.x2 and self.x2 >= other.x1 and
                self.y1 <= other.y2 and self.y2 >= other.y1)

def carve_room(game_map, room):
    for y in range(room.y1, room.y2):
        for x in range(room.x1, room.x2):
            game_map[y][x] = '.'

def carve_h_corridor(game_map, x1, x2, y):
    for x in range(min(x1, x2), max(x1, x2) + 1):
        game_map[y][x] = '.'

def carve_v_corridor(game_map, y1, y2, x):
    for y in range(min(y1, y2), max(y1, y2) + 1):
        game_map[y][x] = '.'

def generate_dungeon(w, h, max_rooms=10, min_size=4, max_size=8):
    game_map = make_empty_map(w, h)
    rooms = []

    for _ in range(max_rooms):
        rw = random.randint(min_size, max_size)
        rh = random.randint(min_size, max_size)
        rx = random.randint(1, w - rw - 1)
        ry = random.randint(1, h - rh - 1)
        new_room = Rect(rx, ry, rw, rh)

        if any(new_room.intersects(r) for r in rooms):
            continue  # overlaps, skip

        carve_room(game_map, new_room)

        if rooms:
            prev_x, prev_y = rooms[-1].center()
            new_x, new_y = new_room.center()
            if random.random() < 0.5:
                carve_h_corridor(game_map, prev_x, new_x, prev_y)
                carve_v_corridor(game_map, prev_y, new_y, new_x)
            else:
                carve_v_corridor(game_map, prev_y, new_y, prev_x)
                carve_h_corridor(game_map, prev_x, new_x, new_y)

        rooms.append(new_room)

    return game_map, rooms
```

Player starting position: `rooms[0].center()`. Stairs down: `rooms[-1].center()`.

---

## 4. Player Movement & Collision

```python
class Entity:
    def __init__(self, x, y, char, color=0):
        self.x, self.y = x, y
        self.char = char
        self.color = color

    def move(self, dx, dy, game_map):
        nx, ny = self.x + dx, self.y + dy
        if game_map[ny][nx] != '#':   # walkable check
            self.x, self.y = nx, ny

# In your input loop:
key = stdscr.getch()
if key == ord('w'): player.move(0, -1, game_map)
elif key == ord('s'): player.move(0, 1, game_map)
elif key == ord('a'): player.move(-1, 0, game_map)
elif key == ord('d'): player.move(1, 0, game_map)
```

---

## 5. Simple Field of View / Fog of War

The cheap-but-effective version: reveal tiles within a radius, ignoring walls (true line-of-sight is much more code).

```python
def update_visibility(game_map, visible, seen, player, radius=6):
    px, py = player.x, player.y
    h, w = len(game_map), len(game_map[0])
    for y in range(h):
        for x in range(w):
            visible[y][x] = False

    for y in range(max(0, py - radius), min(h, py + radius + 1)):
        for x in range(max(0, px - radius), min(w, px + radius + 1)):
            if (x - px) ** 2 + (y - py) ** 2 <= radius ** 2:
                visible[y][x] = True
                seen[y][x] = True

def draw_with_fog(stdscr, game_map, visible, seen):
    for y, row in enumerate(game_map):
        for x, tile in enumerate(row):
            if visible[y][x]:
                stdscr.addch(y, x, tile, curses.A_BOLD)
            elif seen[y][x]:
                stdscr.addch(y, x, tile, curses.A_DIM)
            # else: draw nothing (unexplored = blank)
```

Initialize `visible`/`seen` as same-size grids of `False`:
```python
visible = [[False]*w for _ in range(h)]
seen = [[False]*w for _ in range(h)]
```

For *real* line-of-sight (blocked by walls), look up "recursive shadowcasting" or "Bresenham line" algorithms when you're back online — the radius method above is a fine placeholder.

---

## 6. Monsters & Items as Entities

```python
class Monster(Entity):
    def __init__(self, x, y, char, hp, power):
        super().__init__(x, y, char)
        self.hp = hp
        self.power = power
        self.alive = True

    def take_turn(self, player, game_map):
        # naive: move toward player if adjacent-ish, else random wander
        dx = (player.x > self.x) - (player.x < self.x)
        dy = (player.y > self.y) - (player.y < self.y)
        if abs(player.x - self.x) + abs(player.y - self.y) < 8:
            self.move(dx, dy, game_map)
        else:
            self.move(random.choice([-1,0,1]), random.choice([-1,0,1]), game_map)

monsters = [Monster(x, y, 'g', hp=5, power=2) for x, y in spawn_points]
```

Combat: just compare positions each turn — if monster and player share a tile (or are adjacent and player attacks), subtract HP.

---

## 7. Minimal Full Skeleton

```python
import curses, random

# --- (paste Rect, carve_room, carve_h_corridor, carve_v_corridor,
#      generate_dungeon, Entity classes from above here) ---

def main(stdscr):
    curses.curs_set(0)
    curses.start_color()
    curses.init_pair(1, curses.COLOR_YELLOW, curses.COLOR_BLACK)

    h, w = 20, 50
    game_map, rooms = generate_dungeon(w, h)
    px, py = rooms[0].center()
    player = Entity(px, py, '@', 1)

    while True:
        stdscr.clear()
        for y, row in enumerate(game_map):
            stdscr.addstr(y, 0, ''.join(row))
        stdscr.addch(player.y, player.x, player.char, curses.color_pair(player.color))
        stdscr.refresh()

        key = stdscr.getch()
        if key == ord('q'):
            break
        elif key == ord('w'): player.move(0, -1, game_map)
        elif key == ord('s'): player.move(0, 1, game_map)
        elif key == ord('a'): player.move(-1, 0, game_map)
        elif key == ord('d'): player.move(1, 0, game_map)

curses.wrapper(main)
```

This alone gives you: a randomly generated dungeon, walkable with WASD, rendered live in your terminal. Everything else (fog of war, monsters, items, combat, stairs to next level) layers on top of this skeleton.

---

## 8. Stretch Goals (roughly in order of effort)

1. Add stairs (`>`) at `rooms[-1].center()`, press a key to descend and regenerate the map
2. Add HP/inventory display in a side panel (just more `addstr` calls at fixed coordinates)
3. Add monsters with the `Monster` class above, give them turns after the player moves
4. Add fog of war using section 5
5. Add items (potions, scrolls) as another `Entity` subtype, pick up on walk-over
6. Save/load game state with `pickle` or `json`
7. Real shadowcasting FOV (look this up later — it's the biggest jump in complexity)

---

## 9. Quick Debugging Notes

- If your terminal looks broken after a crash, run `reset` (or `tput reset`) — `curses.wrapper` *should* prevent this but doesn't always catch every exception.
- `addstr`/`addch` will throw an error if you write to the very last cell of the terminal (bottom-right corner) — it's a known curses quirk. Either avoid writing there or wrap in `try/except`.
- Terminal too small → `stdscr.getmaxyx()` to check dimensions before drawing, and design your map to fit.
