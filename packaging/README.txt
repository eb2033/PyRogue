PyRogue
=======

A turn-based roguelike dungeon crawler written in Python.

Running it
----------
Unzip the whole folder somewhere you can write to (your Desktop or Documents
is fine) and run:

  Windows:  PyRogue\PyRogue.exe
  Linux:    PyRogue/PyRogue

Keep the exe next to its _internal folder -- the game needs both. No Python
installation is required.

Windows SmartScreen may warn that the app is from an "unknown publisher"
because the build is not code-signed. Choose "More info" -> "Run anyway".

Controls
--------
  W A S D       move (walk into a monster to attack)
  Arrow keys    Warrior: move.  Archer: shoot an arrow in that direction
  .             wait a turn
  e             go down the stairs (>) when standing on them
  Shift+S       save
  Shift+L       load
  q             quit
  F11           fullscreen

The menus also take the mouse.

Walk onto a chest to open it: pink chests hold a healing potion, cyan ones a
weapon or armour. Gear equips itself if it's better than what you wear.

Saves and crash.log
-------------------
  Windows:  %APPDATA%\PyRogue
  Linux:    ~/.local/share/pyrogue

If the game ever closes by itself, crash.log there says why.

Settings (optional)
-------------------
Create a file called .env next to the program, with lines like:

  MAP_WIDTH=40
  MAP_HEIGHT=20
  FOV_RADIUS=8
  TURN_DELAY_MS=0      (monsters move instantly)
  TILES=0              (letters instead of tiles)

Licence
-------
PyRogue is MIT-licensed -- see LICENSE in this folder. The game also
contains other people's software, art and fonts under their own licences:
see THIRD_PARTY_NOTICES.txt and the licenses folder.
