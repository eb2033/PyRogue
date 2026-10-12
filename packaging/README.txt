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

Walk onto a chest (=) to open it. Gear equips automatically.

Licence
-------
MIT -- see LICENSE in this folder. The bundled Python runtime and
libraries (pygame-ce, SDL) are distributed under their own licences.
