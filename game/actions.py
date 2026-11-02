"""The semantic actions a renderer hands to GameState.handle_action.

Standard library only: the vocabulary lives with the game, not the renderer.
render.base re-exports Action so existing imports keep working.
"""


class Action:
    """Valid return values from Renderer.get_action()."""

    MOVE_N = 'move_n'
    MOVE_S = 'move_s'
    MOVE_W = 'move_w'
    MOVE_E = 'move_e'
    # Arrow keys. For a warrior these behave exactly like MOVE_* (walk /
    # bump-attack); for an archer they fire an arrow instead of moving.
    # GameState decides which, based on player.char_class -- the renderer
    # doesn't need to know about classes at all.
    SHOOT_N = 'shoot_n'
    SHOOT_S = 'shoot_s'
    SHOOT_W = 'shoot_w'
    SHOOT_E = 'shoot_e'
    WAIT = 'wait'
    DESCEND = 'descend'
    QUIT = 'quit'
    # 'r': only on the game-over screen ('press r to restart'), where it ends
    # the run and sends the player back to the title screen. Mid-game it does
    # nothing.
    RESTART = 'restart'
    # 'q': the class ability (the archer primes a hop, whose direction the
    # next movement key picks; the warrior parries). On the game-over screen
    # GameState treats it as "quit".
    ABILITY = 'ability'
    # Keys 1-3: take that card of an opened chest's choice (GameState.choose).
    # Outside a choice they do nothing.
    CHOOSE_1 = 'choose_1'
    CHOOSE_2 = 'choose_2'
    CHOOSE_3 = 'choose_3'
    # In the shop (GameState.shop_open), keys 1-5 buy that offer
    # (GameState.buy); CHOOSE_4/CHOOSE_5 only mean something there.
    CHOOSE_4 = 'choose_4'
    CHOOSE_5 = 'choose_5'
    # Key 4 (and Space, but only while a choice is on screen): leave the
    # chest's or shrine's offers and take nothing (GameState.skip_choice), or
    # leave the shop.
    SKIP = 'skip'
    # 'h': drink the first potion on the belt (GameState.drink_from_belt).
    DRINK = 'drink'
