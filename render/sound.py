"""Plays the sound events game logic records (game/sound.py).

`SoundBoard` looks for `<directory>/<slot>.ogg`, else `.wav`, per slot. It
never raises and never blocks the game: no mixer or audio device, a missing
directory, or a missing or corrupt file just means silence. The mixer (an
audio device) is opened only when the first slot finds a file, so a game with
no sound files never touches the audio system. May import
pygame; only render/pygame_render.py and main.make_renderer import this.
"""

from pathlib import Path

import pygame

from game.sound import SoundEvent

EXTENSIONS = ('.ogg', '.wav')


class SoundBoard:
    def __init__(self, directory: Path | None, enabled: bool = True):
        self.directory = directory
        self.enabled = enabled
        # Cursor: the serial of the newest event handled; a redraw of the
        # same round re-offers the same events, which must not play twice.
        self.last_serial = 0
        # slot -> Sound, or None for "no usable file" (looked up only once).
        self._cache: dict[str, pygame.mixer.Sound | None] = {}
        self._mixer_open = False  # opened lazily: _mixer_ready

    @classmethod
    def silent(cls):
        """A disabled board: the renderer's default."""
        return cls(None, enabled=False)

    def reset(self):
        """A new run's serials start over; forget the old high-water mark."""
        self.last_serial = 0

    def sound_for(self, slot: str) -> 'pygame.mixer.Sound | None':
        if slot not in self._cache:
            self._cache[slot] = self._load(slot)
        return self._cache[slot]

    def _mixer_ready(self):
        """Open the mixer if it isn't open yet; on failure the board turns
        itself off (silent from then on). True if sounds can be loaded."""
        if not self.enabled:
            return False
        if self._mixer_open:
            return True
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            self._mixer_open = True
        except Exception:
            self.enabled = False
        return self.enabled

    def _load(self, slot):
        if self.directory is None:
            return None
        for ext in EXTENSIONS:
            path = self.directory / (slot + ext)
            try:
                if path.is_file():
                    if not self._mixer_ready():
                        return None
                    return pygame.mixer.Sound(str(path))
            except Exception:
                continue
        return None

    def play_new(self, events):
        """Play the SoundEvents in `events` (GameState.events: the other
        records are skipped) newer than the cursor, oldest first."""
        for event in events:
            if event.serial <= self.last_serial:
                continue
            self.last_serial = event.serial
            if not isinstance(event, SoundEvent):
                continue
            if self.enabled:
                try:
                    sound = self.sound_for(event.slot)
                    if sound is not None:
                        sound.play()
                except Exception:
                    pass
