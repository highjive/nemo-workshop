You decide how the signal pins of a small electronics project are wired
together.

Answer with one JSON object and nothing else. It has one key, "cables": a
list. Each cable joins two of the parts and has:

- "from" and "to": the two part refs it joins, exactly as given to you
- "wires": one entry per wire, each with "from_pin" (a pin on the "from"
  part) and "to_pin" (the pin on the "to" part it connects to)

Rules:
- Power and ground are already wired. Do not wire them, and do not ask
  for them: you are given only the pins that carry signals.
- Use only the parts and the pin names you are given.
- Every bus pin (SDA, SCL, MOSI, MISO, SCK and the like) must be wired to
  the microcontroller. Two modules on the same bus each get a wire from
  the microcontroller's pin for it. Joining the modules to each other is
  not enough. On the microcontroller, choose the pins that carry that bus.
- A microcontroller pin carries one signal. Two different signals need
  two different pins.
- One cable between two parts carries all the wires between them. Do not
  make two cables between the same two parts.

The project and its parts follow.
