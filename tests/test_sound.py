"""SoundBoard: plays slot files once per event, and is silent when it can't."""

import os
import tempfile
import unittest
import wave
from pathlib import Path
from typing import cast
from unittest import mock

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

try:
    import pygame
except ImportError:  # pragma: no cover - terminal-only checkout
    pygame = None

import main
from game.sound import SoundEvent
from game.state import GameState

if pygame is not None:
    from render.pygame_render import PygameRenderer
    from render.sound import SoundBoard


def write_wav(path, ms=10):
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b'\x00\x00' * (22050 * ms // 1000))


@unittest.skipIf(pygame is None, 'pygame-ce not installed')
class SoundBoardTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_missing_directory_is_silent(self):
        board = SoundBoard(Path('/nonexistent'), enabled=True)
        board.play_new([SoundEvent(1, 'door')])
        self.assertEqual(board.last_serial, 1)
        self.assertIsNone(board.sound_for('door'))
        self.assertFalse(SoundBoard.silent().enabled)
        # a disabled board plays nothing even with a file
        write_wav(self.dir / 'door.wav')
        board = SoundBoard(self.dir, enabled=False)
        with mock.patch('pygame.mixer.Sound') as sound:
            board.play_new([SoundEvent(1, 'door')])
        sound.assert_not_called()
        self.assertEqual(board.last_serial, 1)

    def test_plays_only_the_sound_events_of_the_stream(self):
        """GameState.events mixes every record type; only SoundEvents play,
        once each, in order."""
        write_wav(self.dir / 'door.wav')
        state = GameState(40, 20, seed=0)
        state.events.clear()
        state.sound('door')
        state.attack(state.player, state.player)  # a Hit between two sounds
        state.sound('door')
        with mock.patch('pygame.mixer.Sound') as sound:
            board = SoundBoard(self.dir, enabled=True)
            board.play_new(state.events)
            board.play_new(state.events)
        self.assertEqual(sound.return_value.play.call_count, 2)
        self.assertEqual(board.last_serial, state.events[-1].serial)

    def test_mixer_failure_is_silent(self):
        write_wav(self.dir / 'door.wav')
        with (
            mock.patch('pygame.mixer.get_init', return_value=None),
            mock.patch('pygame.mixer.init', side_effect=pygame.error('no audio')),
            mock.patch('pygame.mixer.Sound') as sound,
        ):
            board = SoundBoard(self.dir, enabled=True)
            board.play_new([SoundEvent(1, 'door'), SoundEvent(2, 'door')])
        self.assertFalse(board.enabled)
        sound.assert_not_called()
        self.assertEqual(board.last_serial, 2)

    def test_mixer_waits_for_the_first_sound_file(self):
        """No files, no mixer: an audio device is opened only once a slot
        finds a file to play, and only once."""
        with (
            mock.patch('pygame.mixer.get_init', return_value=None),
            mock.patch('pygame.mixer.init') as init,
            mock.patch('pygame.mixer.Sound'),
        ):
            board = SoundBoard(self.dir, enabled=True)
            board.play_new([SoundEvent(1, 'door')])
            init.assert_not_called()
            write_wav(self.dir / 'descend.wav')
            write_wav(self.dir / 'hit.wav')
            board.play_new([SoundEvent(2, 'descend'), SoundEvent(3, 'hit')])
            init.assert_called_once_with()
        self.assertTrue(board.enabled)

    def test_reset_lets_a_new_run_play_from_serial_one_and_events_play_once(self):
        write_wav(self.dir / 'door.wav')
        board = SoundBoard(self.dir)
        with mock.patch('pygame.mixer.Sound') as sound:
            board.play_new([SoundEvent(5, 'door')])
            board.play_new([SoundEvent(1, 'door')])
            self.assertEqual(sound.return_value.play.call_count, 1)
            board.reset()
            board.play_new([SoundEvent(1, 'door')])
            self.assertEqual(sound.return_value.play.call_count, 2)
        # the same event across redraws plays once
        board = SoundBoard(self.dir)
        events = [SoundEvent(1, 'door')]
        with mock.patch('pygame.mixer.Sound') as sound:
            board.play_new(events)
            board.play_new(events)
        self.assertEqual(sound.return_value.play.call_count, 1)

    def test_events_play_in_order(self):
        board = SoundBoard(self.dir)
        sounds = {'door': mock.Mock(), 'descend': mock.Mock()}
        order = mock.Mock()
        order.attach_mock(sounds['door'].play, 'door')
        order.attach_mock(sounds['descend'].play, 'descend')
        with mock.patch.object(board, 'sound_for', side_effect=sounds.get):
            board.play_new([SoundEvent(1, 'door'), SoundEvent(2, 'descend')])
        self.assertEqual([c[0] for c in order.mock_calls], ['door', 'descend'])
        self.assertEqual(board.last_serial, 2)

    def test_missing_file_is_looked_up_once(self):
        board = SoundBoard(self.dir)
        with mock.patch('pygame.mixer.Sound') as sound:
            self.assertIsNone(board.sound_for('door'))
            self.assertIsNone(board.sound_for('door'))
        sound.assert_not_called()

    def test_ogg_preferred_over_wav(self):
        write_wav(self.dir / 'door.wav')
        (self.dir / 'door.ogg').write_bytes(b'x')
        board = SoundBoard(self.dir)
        with mock.patch('pygame.mixer.Sound') as sound:
            board.sound_for('door')
        sound.assert_called_once_with(str(self.dir / 'door.ogg'))

    def test_corrupt_file_is_skipped(self):
        (self.dir / 'door.wav').write_bytes(b'garbage')
        write_wav(self.dir / 'descend.wav')
        board = SoundBoard(self.dir)
        real = pygame.mixer.Sound
        played = []

        class Spy:
            def __init__(self, path):
                self.sound = real(path)  # garbage raises here, like the real thing

            def play(self):
                played.append(self.sound)

        with mock.patch('pygame.mixer.Sound', Spy):
            board.play_new([SoundEvent(1, 'door'), SoundEvent(2, 'descend')])
        self.assertEqual(len(played), 1)
        self.assertIsNone(board.sound_for('door'))


@unittest.skipIf(pygame is None, 'pygame-ce not installed')
class RendererSoundTest(unittest.TestCase):
    def test_renderer_plays_state_sounds_on_draw(self):
        board = mock.Mock()
        renderer = PygameRenderer(40, 20, sound=board)
        try:
            state = GameState(40, 20, seed=0)
            state.events.append(SoundEvent(1, 'door'))
            renderer.draw(state)
            board.play_new.assert_called_once_with(state.events)
        finally:
            renderer.close()

    def test_a_new_game_state_resets_the_board(self):
        write_wav_dir = tempfile.TemporaryDirectory()
        self.addCleanup(write_wav_dir.cleanup)
        write_wav(Path(write_wav_dir.name) / 'door.wav')
        board = SoundBoard(Path(write_wav_dir.name))
        renderer = PygameRenderer(40, 20, sound=board)
        try:
            a, b = GameState(40, 20, seed=0), GameState(40, 20, seed=0)
            a.events.append(SoundEvent(5, 'door'))
            b.events.append(SoundEvent(1, 'door'))
            with mock.patch('pygame.mixer.Sound') as sound:
                renderer.draw(a)
                renderer.draw(a)
                self.assertEqual(sound.return_value.play.call_count, 1)
                renderer.draw(b)
                self.assertEqual(sound.return_value.play.call_count, 2)
        finally:
            renderer.close()

    def test_default_renderer_is_silent_and_make_renderer_respects_sound_0(self):
        renderer = PygameRenderer(40, 20)
        try:
            self.assertFalse(renderer.sound.enabled)
        finally:
            renderer.close()
        with mock.patch.dict(os.environ, {'SOUND': '0'}):
            renderer = cast(PygameRenderer, main.make_renderer(40, 20))
        try:
            self.assertFalse(renderer.sound.enabled)
        finally:
            renderer.close()


if __name__ == '__main__':
    unittest.main()
