"""Rendering front ends.

Each renderer implements render.base.Renderer. The curses one is standard
library only; the pygame one (pygame_render.py and the ui/screens/tileset/
input_map modules it uses) depends on pygame-ce. Game logic stays clean of both.
"""
