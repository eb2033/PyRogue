"""The browser build's game loop: main.py's loop with `await` on the renderer.

Each function mirrors its twin in main.py, same calls in the same order; only
the renderer's waiting calls (draw, get_action, pause, show_title_screen,
choose_class) are awaited, so the page can repaint between them. Web-only code.
"""

from game.state import GameState


async def resolve_player_strikes(renderer, state, delay_ms):
    """Drive the rest of the player's half: a rapier's queued second strike.

    Draw the landed strike (its beat plays), hold the frame, then roll the next.
    """
    while state.strike_pending():
        await renderer.draw(state)
        await renderer.pause(delay_ms)
        state.step_strike()


async def resolve_monster_phase(renderer, state, delay_ms):
    """Drive the monster half one visible step at a time.

    Draw before each monster acts and hold the frame only when the step was
    visible, so crossing an empty dungeon costs no pauses.
    """
    while state.monster_phase_pending():
        await renderer.draw(state)
        if state.step_monster_phase():
            await renderer.pause(delay_ms)


async def run(renderer, state, delay_ms=110):
    while state.running:
        await renderer.draw(state)
        state.handle_action(await renderer.get_action())
        await resolve_player_strikes(renderer, state, delay_ms)
        await resolve_monster_phase(renderer, state, delay_ms)


async def play(renderer, width, height, fov_radius=6, delay_ms=110):
    """Title screen, class select, a run -- and again while runs end in restart.
    Every way out ends on the goodbye screen: a browser tab can't close itself."""
    while await renderer.show_title_screen():
        state = GameState(
            width, height, fov_radius=fov_radius, char_class=await renderer.choose_class()
        )
        await run(renderer, state, delay_ms)
        if not state.restart_requested:
            break
    await renderer.show_goodbye()
