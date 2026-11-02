"""In-window menu screens and overlays. Owned by WS-D.

Paint-only: each function draws one frame onto a ui.Canvas. The event loop
that drives a menu (waiting for keys, moving the render.menu.Menu cursor) lives
in pygame_render.py, so these stay testable without input. Mouse hover/click
goes through option_at ("which option is at this pixel"), which that loop
calls; it shares paint_menu's geometry. Keyboard stays mandatory.
"""

import textwrap

import pygame

from render import choice, palette, shop_text

TITLE_OPTIONS = ['Start', 'Quit']
CLASS_OPTIONS = ['Warrior', 'Archer']
CLASS_DESCRIPTIONS = {
    'warrior': 'Melee. Walk into an enemy to hit it.',
    'archer': 'Ranged. WASD moves, arrow keys fire.',
}
MENU_HINT = 'up/down or w/s to choose, enter to select, q to quit'
GAME_OVER_TITLE = 'YOU DIED'
GAME_OVER_HINT = 'press q to quit'
GAME_OVER_RESTART_HINT = 'press r to restart'
# The hint lines under the title, top to bottom.
GAME_OVER_HINTS = (GAME_OVER_HINT, GAME_OVER_RESTART_HINT)
GAME_OVER_SCALE = 4  # the title is this many times the map's font


def _menu_geometry(layout, options, banner_lines):
    """(banner top row, first option row). Option i is on row
    `options_top + 2 * i`; paint_menu and option_at both use this."""
    top = max(1, layout.rows // 2 - len(banner_lines) - len(options) - 2)
    return top, top + len(banner_lines) + 2


def _option_text(option, selected):
    return f'> {option} <' if selected else f'  {option}  '


def paint_menu(canvas, menu, banner_lines, descriptions=None):
    """A banner, the menu's options (selected one highlighted), and the
    selected option's description, centred in the text grid."""
    rows = canvas.layout.rows
    options = menu.options
    top, options_top = _menu_geometry(canvas.layout, options, banner_lines)
    for i, line in enumerate(banner_lines):
        canvas.put_str_centered(top + i, line, palette.PLAYER)

    for i, option in enumerate(options):
        if i == menu.index:
            canvas.put_str_centered(
                options_top + i * 2, _option_text(option, True), palette.BACKGROUND, palette.TEXT
            )
            description = (descriptions or {}).get(option.lower())
            if description:
                canvas.put_str_centered(options_top + len(options) * 2 + 1, description)
        else:
            canvas.put_str_centered(options_top + i * 2, _option_text(option, False))

    # A narrow grid (the panel stacked under the map) can't fit the hint on
    # one line: wrap it upwards from the usual row.
    hint = textwrap.wrap(MENU_HINT, max(1, canvas.layout.cols)) or ['']
    for i, line in enumerate(hint):
        canvas.put_str_centered(rows - 1 - len(hint) + i, line)


def option_at(layout, menu, banner_lines, pixel):
    """Index of the menu option under window pixel `pixel`, or None.

    Hit-testing for mouse hover/click; pygame_render's _run_menu calls it with
    the same `layout`, `menu` and `banner_lines` it painted with. An option's
    hit area is exactly its own text row (the blank rows between options hit
    nothing), across the columns the *widest* option's text spans as
    paint_menu centres it -- so every option has the same, generous width,
    and the mouse need not land on the letters of a short one.
    """
    options = menu.options
    if not options:
        return None
    _, options_top = _menu_geometry(layout, options, banner_lines)
    px, py = pixel
    if py < layout.origin_y:
        return None
    row = (py - layout.origin_y) // layout.cell_h
    index, odd = divmod(row - options_top, 2)
    if odd or not 0 <= index < len(options) or row >= layout.rows:
        return None
    # Same centring and clipping as Canvas.put_str_centered / put_str.
    width = max(len(_option_text(option, False)) for option in options)
    left = max(0, (layout.cols - width) // 2)
    right = min(layout.cols, left + width)
    x0 = layout.origin_x + left * layout.cell_w
    x1 = layout.origin_x + right * layout.cell_w
    return index if x0 <= px < x1 else None


def game_over_fonts(layout):
    """(title font, hint font). The title is GAME_OVER_SCALE times the map's
    font, shrunk back toward it if it wouldn't fit across the map."""
    room = layout.map_rect().width - 2 * layout.cell_w
    size = layout.font_size * GAME_OVER_SCALE
    while size > layout.font_size and layout._font(size).size(GAME_OVER_TITLE)[0] > room:
        size -= 1
    return layout._font(size), layout.font


def game_over_rect(layout):
    """Pixel rect of the game-over banner: a box centred across the top of
    the map, holding the big title and the hint lines under it."""
    title_font, hint_font = game_over_fonts(layout)
    text_w = max(
        title_font.size(GAME_OVER_TITLE)[0],
        *(hint_font.size(hint)[0] for hint in GAME_OVER_HINTS),
    )
    text_h = title_font.get_linesize() + len(GAME_OVER_HINTS) * hint_font.get_linesize()
    box = pygame.Rect(0, 0, text_w + 2 * layout.cell_w, text_h + layout.cell_h)
    area = layout.map_rect()
    box.centerx = area.centerx
    box.top = area.top + layout.cell_h // 2
    return box


def paint_game_over(canvas):
    """Overlay drawn on top of the final game frame: the title and the hint
    lines in a framed box placed by game_over_rect."""
    layout = canvas.layout
    box = game_over_rect(layout)
    canvas.surface.fill(palette.BACKGROUND, box)
    pygame.draw.rect(canvas.surface, palette.DANGER, box, max(1, layout.cell_h // 12))
    title_font, hint_font = game_over_fonts(layout)
    title = title_font.render(GAME_OVER_TITLE, True, palette.DANGER)
    top = box.top + layout.cell_h // 2
    canvas.surface.blit(title, title.get_rect(centerx=box.centerx, top=top))
    top += title_font.get_linesize()
    for line in GAME_OVER_HINTS:
        hint = hint_font.render(line, True, palette.DANGER)
        canvas.surface.blit(hint, hint.get_rect(centerx=box.centerx, top=top))
        top += hint_font.get_linesize()


def _choice_text_w(layout, lines):
    return max((layout.font.size(line)[0] for line in lines), default=0)


def choice_rects(layout, state):
    """(box, card rects, compact) for state.pending_choice -- see
    _choice_geometry, which also gives the skip line's rect."""
    box, cards, compact, _ = _choice_geometry(layout, state)
    return box, cards, compact


def choice_skip_rect(layout, state):
    """The skip line's rect (under the cards) for state.pending_choice."""
    return _choice_geometry(layout, state)[3]


def _choice_geometry(layout, state):
    """(box, card rects, compact, skip rect) for state.pending_choice: a box
    centred on the map with a title row, the cards, the skip line and a hint
    row (half a line of margin round each). Cards go side by side
    when three fit across the map, else they stack in two-line compact form.
    paint_choice, choice_card_at and choice_skip_at all use this."""
    items = state.pending_choice or []
    numbered = choice.cards(items)
    line_h = layout.font.get_linesize()
    pad = layout.cell_w
    area = layout.map_rect()
    title = choice.title(items)
    skip_w = layout.font.size(choice.skip_line(items))[0] + 2 * pad
    skip_h = line_h + line_h // 2  # the skip line and its margin above
    frame_w = max(layout.font.size(title)[0], layout.font.size(choice.HINT)[0], skip_w)

    full = [line for n, item in numbered for line in choice.card_lines(n, item)]
    card_w = _choice_text_w(layout, full) + 2 * pad
    card_h = (len(full) // max(1, len(items))) * line_h + line_h
    gap = pad
    box_w = max(len(items) * card_w + (len(items) - 1) * gap, frame_w) + 2 * pad
    box_h = card_h + 4 * line_h + skip_h
    compact = box_w > area.width or box_h > area.height
    if compact:
        lines = [line for n, item in numbered for line in choice.compact_lines(n, item)]
        card_w = _choice_text_w(layout, lines) + 2 * pad
        card_h = 2 * line_h + line_h // 2
        gap = max(1, line_h // 4)
        box_w = max(card_w, frame_w) + 2 * pad
        box_h = len(items) * card_h + (len(items) - 1) * gap + 4 * line_h + skip_h

    box = pygame.Rect(0, 0, box_w, box_h)
    box.center = area.center
    top = box.top + 2 * line_h
    cards = []
    if compact:
        for i in range(len(items)):
            rect = pygame.Rect(0, top + i * (card_h + gap), card_w, card_h)
            rect.centerx = box.centerx
            cards.append(rect)
    else:
        row_w = len(items) * card_w + (len(items) - 1) * gap
        left = box.centerx - row_w // 2
        cards = [
            pygame.Rect(left + i * (card_w + gap), top, card_w, card_h) for i in range(len(items))
        ]
    cards_bottom = max((rect.bottom for rect in cards), default=top)
    skip = pygame.Rect(0, cards_bottom + line_h // 2, skip_w, line_h)
    skip.centerx = box.centerx
    return box, cards, compact, skip


def choice_card_at(layout, state, pixel):
    """Index into state.pending_choice of the card under window pixel
    `pixel`, or None (not choosing, or not on a card)."""
    if state is None or not state.is_choosing:
        return None
    _, cards, _ = choice_rects(layout, state)
    for i, rect in enumerate(cards):
        if rect.collidepoint(pixel):
            return i
    return None


def choice_skip_at(layout, state, pixel):
    """True if window pixel `pixel` is on the skip line of a pending choice."""
    if state is None or not state.is_choosing:
        return False
    return choice_skip_rect(layout, state).collidepoint(pixel)


def paint_choice(canvas, state):
    """Overlay for a pending choice: a dark framed box over the map, TEXT
    for the title and hint, and each card a parchment page (the panel's
    paper) inked in its item's rarity colour -- or, for a shrine's boons,
    the boon's colour (render/choice.py has every card's text)."""
    layout = canvas.layout
    surface = canvas.surface
    box, cards, compact, skip = _choice_geometry(layout, state)
    border = max(1, layout.cell_h // 12)
    line_h = layout.font.get_linesize()
    surface.fill(palette.BACKGROUND, box)
    pygame.draw.rect(surface, palette.PAGE_EDGE, box, border)

    title = canvas.text_surface(choice.title(state.pending_choice), palette.TEXT, bold=True)
    surface.blit(title, title.get_rect(centerx=box.centerx, top=box.top + line_h // 2))
    hint = canvas.text_surface(choice.HINT, palette.TEXT)
    surface.blit(hint, hint.get_rect(centerx=box.centerx, bottom=box.bottom - line_h // 2))
    skip_text = canvas.text_surface(choice.skip_line(state.pending_choice), palette.TEXT)
    surface.blit(skip_text, skip_text.get_rect(center=skip.center))

    for (number, item), rect in zip(choice.cards(state.pending_choice), cards):
        surface.fill(palette.PAGE, rect)
        pygame.draw.rect(surface, palette.PAGE_EDGE, rect, border)
        ink = palette.ink(item.color)
        lines = (choice.compact_lines if compact else choice.card_lines)(number, item)
        top = rect.top + (rect.height - len(lines) * line_h) // 2
        for i, line in enumerate(lines):
            text = canvas.text_surface(line, ink, bold=(i == 0))
            if compact:
                at = text.get_rect(left=rect.left + layout.cell_w, top=top + i * line_h)
            else:
                at = text.get_rect(centerx=rect.centerx, top=top + i * line_h)
            surface.blit(text, at)


def _shop_geometry(layout, state, bounds=None):
    """(box, row rects) for the open shop: a box centred on the map with a
    title, the gold line, five two-line offer rows and the hint (half a line
    of margin round each, and a whole one under the gold line).

    The box is as big as its text needs, not clamped to the map: glyph
    mode's map is far too small for an offer's price, so the box may cover
    the boards. Given `bounds` (the window), it is shrunk to fit and pushed
    inside them; only text that still doesn't fit is clipped by the box."""
    line_h = layout.font.get_linesize()
    pad = layout.cell_w
    area = layout.map_rect()
    lines = [
        line
        for n, offer in enumerate(state.shop.offers, start=1)
        for line in shop_text.offer_lines(n, offer, state.player)
    ]
    texts = [shop_text.TITLE, shop_text.HINT, shop_text.gold_line(state.player), *lines]
    row_w = _choice_text_w(layout, texts) + 2 * pad
    row_h = 2 * line_h + line_h // 2
    gap = max(1, line_h // 4)
    count = len(state.shop.offers)
    head_h = 3 * line_h  # title and gold line, half a line round each
    box = pygame.Rect(
        0, 0, row_w + 2 * pad, head_h + count * row_h + (count - 1) * gap + 2 * line_h
    )
    box.center = area.center
    if bounds is not None:
        box.size = (min(box.width, bounds.width), min(box.height, bounds.height))
        box.center = area.center
        box = box.clamp(bounds)
    inner_w = max(1, box.width - 2 * pad)
    top = box.top + head_h
    rows = []
    for i in range(count):
        rect = pygame.Rect(0, top + i * (row_h + gap), min(row_w, inner_w), row_h)
        rect.centerx = box.centerx
        rows.append(rect)
    return box, rows


def _shop_lines(layout, state, bounds=None):
    """(box, rows, [(text, rect, offer or None, bold)]) for every line the
    shop paints, each at the rect its text takes."""
    box, rows = _shop_geometry(layout, state, bounds)
    line_h = layout.font.get_linesize()
    font = layout.font

    def place(text, offer=None, bold=False, **at):
        font.set_bold(bold)  # measured as Canvas.text_surface renders it
        try:
            size = font.size(text)
        finally:
            font.set_bold(False)
        return text, pygame.Rect((0, 0), size).move_to(**at), offer, bold

    placed = [
        place(shop_text.TITLE, bold=True, centerx=box.centerx, top=box.top + line_h // 2),
        place(
            shop_text.gold_line(state.player),
            centerx=box.centerx,
            top=box.top + line_h + line_h // 2,
        ),
        place(shop_text.HINT, centerx=box.centerx, bottom=box.bottom - line_h // 2),
    ]
    for number, (offer, rect) in enumerate(zip(state.shop.offers, rows), start=1):
        lines = shop_text.offer_lines(number, offer, state.player)
        top = rect.top + (rect.height - len(lines) * line_h) // 2
        for i, line in enumerate(lines):
            left = rect.left + layout.cell_w
            placed.append(place(line, offer, i == 0, left=left, top=top + i * line_h))
    return box, rows, placed


def shop_rect(layout, state, bounds=None):
    """The open shop's box (inside `bounds`, the window, if given)."""
    return _shop_geometry(layout, state, bounds)[0]


def shop_row_rects(layout, state, bounds=None):
    """The five offer rows' rects, in key order."""
    return _shop_geometry(layout, state, bounds)[1]


def shop_line_rects(layout, state, bounds=None):
    """[(text, rect)] for every line the shop paints: title, gold, hint and
    each offer's two lines."""
    return [(text, rect) for text, rect, _, _ in _shop_lines(layout, state, bounds)[2]]


def _offer_ink(offer):
    """The offer's own ink, whether or not the player can afford it: only a
    sold offer is greyed."""
    if offer.sold:
        return palette.SEEN
    if offer.kind == 'weapon':
        return palette.ink(offer.item.color)
    if offer.kind == 'boon':
        return palette.ink(offer.boon.color)
    return palette.INK


def paint_shop(canvas, state):
    """Overlay for the open shop: a dark framed box (centred on the map,
    inside the window) with the title, the player's gold, five parchment
    rows inked by the offer (rarity ink for a weapon, the boon's colour,
    plain ink for the heal; greyed, palette.SEEN, once sold) -- an
    unaffordable offer's price in palette.INK_DANGER -- and the hint."""
    layout = canvas.layout
    surface = canvas.surface
    box, rows, placed = _shop_lines(layout, state, surface.get_rect())
    border = max(1, layout.cell_h // 12)
    previous_clip = surface.get_clip()
    surface.set_clip(box)
    surface.fill(palette.BACKGROUND, box)
    pygame.draw.rect(surface, palette.PAGE_EDGE, box, border)
    for rect in rows:
        surface.fill(palette.PAGE, rect)
        pygame.draw.rect(surface, palette.PAGE_EDGE, rect, border)
    for text, rect, offer, bold in placed:
        ink = palette.TEXT if offer is None else _offer_ink(offer)
        price = None if offer is None or bold else shop_text.price_text(offer, state.player)
        if price is None or shop_text.affordable(offer, state.player):
            surface.blit(canvas.text_surface(text, ink, bold=bold), rect)
            continue
        # A detail line the player can't afford: the price, at its end, in red.
        head = text[: -len(price)]
        surface.blit(canvas.text_surface(head, ink), rect)
        price_at = rect.move(layout.font.size(head)[0], 0)
        surface.blit(canvas.text_surface(price, palette.INK_DANGER), price_at)
    surface.set_clip(previous_clip)
