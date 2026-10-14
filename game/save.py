"""Save/load (spec §8.5) via JSON — human-readable, no pickle trust issues.

Serializes just enough to resume: the current map, both fog grids, the
player, and the living monsters/chests on the current level. Regenerating a
fresh dungeon on load is not an option (the player would lose position/HP
continuity), so the exact map is round-tripped as a list of row strings.
"""

import json
import os
from pathlib import Path

from game.entity import Entity
from game.item import Chest, Item, gear_defense
from game.monster import Monster

SAVE_VERSION = 1


def _entity_to_dict(e):
    d = {'x': e.x, 'y': e.y, 'char': e.char, 'color': e.color, 'name': e.name}
    if isinstance(e, Monster):
        d.update(type='monster', kind=e.kind, hp=e.hp, max_hp=e.max_hp,
                  power=e.power, alive=e.alive, is_boss=e.is_boss)
    elif isinstance(e, Chest):
        d.update(type='chest', guaranteed_min_rarity=e.guaranteed_min_rarity,
                 kind=e.kind)
    elif isinstance(e, Item):
        # Only reachable from an old (pre-chest) save file -- current play
        # never leaves a bare Item sitting in state.entities anymore.
        d.update(type='item', kind=e.kind, rarity=e.rarity)
    else:
        d.update(type='entity')
    return d


def _entity_from_dict(d):
    if d['type'] == 'monster':
        m = Monster(d['x'], d['y'], d['kind'], is_boss=d.get('is_boss', False))
        m.hp, m.max_hp, m.power, m.alive = d['hp'], d['max_hp'], d['power'], d['alive']
        return m
    if d['type'] == 'chest':
        # A save from before chests had a kind gets one rolled now.
        return Chest(d['x'], d['y'], d.get('guaranteed_min_rarity'), kind=d.get('kind'))
    if d['type'] == 'item':
        return Item(d['x'], d['y'], d['kind'], d.get('rarity', 'common'))
    e = Entity(d['x'], d['y'], d['char'], color=d['color'], name=d['name'])
    return e


def _gear_to_dict(item):
    return None if item is None else {'kind': item.kind, 'rarity': item.rarity}


def _gear_from_dict(d):
    return None if d is None else Item(0, 0, d['kind'], d['rarity'])


def state_to_dict(state):
    return {
        'version': SAVE_VERSION,
        'width': state.width,
        'height': state.height,
        'fov_radius': state.fov_radius,
        'depth': state.depth,
        'game_over': state.game_over,
        'game_map': [''.join(row) for row in state.game_map],
        'seen': [[bool(c) for c in row] for row in state.seen],
        'messages': state.messages,
        'player': {
            'x': state.player.x, 'y': state.player.y,
            'char_class': state.player.char_class,
            'hp': state.player.hp, 'max_hp': state.player.max_hp,
            'base_power': state.player.base_power, 'power': state.player.power,
            'defense': state.player.defense,
            'weapon': _gear_to_dict(state.player.weapon),
            'armor': _gear_to_dict(state.player.armor),
            'inventory': list(state.player.inventory),
        },
        'entities': [_entity_to_dict(e) for e in state.entities if e is not state.player],
        # An opened chest's offers, stored like equipped gear (kind + rarity;
        # junk has rarity None). None when no choice is pending.
        'pending_choice': (None if state.pending_choice is None
                           else [_gear_to_dict(i) for i in state.pending_choice]),
    }


def apply_dict(state, data):
    """Mutate `state` in place to match a previously saved dict."""
    state.width = data['width']
    state.height = data['height']
    state.fov_radius = data['fov_radius']
    state.depth = data['depth']
    state.game_over = data['game_over']
    state.game_map = [list(row) for row in data['game_map']]
    state.seen = data['seen']
    state.visible = [[False] * state.width for _ in range(state.height)]
    state.messages = data['messages']

    p = data['player']
    state.player.x, state.player.y = p['x'], p['y']
    # get() with fallbacks: saves from before classes/gear existed had no field.
    state.player.char_class = p.get('char_class', 'warrior')
    state.player.hp, state.player.max_hp = p['hp'], p['max_hp']
    state.player.base_power = p.get('base_power', p['power'])
    state.player.power = p['power']
    state.player.weapon = _gear_from_dict(p.get('weapon'))
    state.player.armor = _gear_from_dict(p.get('armor'))
    # Defense comes from the gear (armor, plus a Sword & Shield's), so derive
    # it from the current tables: a save from before ARMOR_DEFENSE stored the
    # old, smaller value. Weapon effects (crit, reach, ...) come from the
    # weapon's kind and rarity; max_hp was saved with any War Axe bonus
    # already in it, so it is restored as saved, not re-applied.
    if state.player.armor is not None or state.player.weapon is not None:
        state.player.defense = gear_defense(state.player)
    else:
        state.player.defense = p.get('defense', 0)
    state.player.inventory = list(p['inventory'])

    # Saves from before chest choices have no field: nothing pending.
    pending = data.get('pending_choice')
    state.pending_choice = None if pending is None else [_gear_from_dict(d) for d in pending]

    state.cancel_monster_phase()  # queued monsters belong to the discarded level
    state.entities = [state.player] + [_entity_from_dict(d) for d in data['entities']]
    state.update_fov()


def save_game(state, path):
    """Write `state` to `path` (str or Path), chosen by the caller -- normally
    game.paths.save_path(). The write goes to a sibling temp file that is then
    renamed over the target, so a crash mid-save can't truncate an existing
    save. The parent directory is created if missing."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(state_to_dict(state))
    tmp = path.with_name(path.name + '.tmp')
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def load_game(path):
    """Returns a dict suitable for apply_dict(), or None if no save exists."""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
