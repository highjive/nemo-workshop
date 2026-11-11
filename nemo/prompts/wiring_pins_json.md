You choose which pin of the microcontroller each signal pin of a small
electronics project is wired to.

Answer with one JSON object and nothing else. It has one key for each part
that is not the microcontroller. Under it, each of that part's pins gets
the microcontroller pin it is wired to.

Rules:
- Power and ground are already wired. You are given only signal pins.
- Two parts on the same bus share the microcontroller's pins for it: the
  same pin for both their SDA, the same pin for both their SCL, and so on.
- Apart from a shared bus, a microcontroller pin carries one signal. Two
  different signals need two different pins.

The project and its parts follow.
