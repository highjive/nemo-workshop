You decide the order in which the parts of a small electronics project sit
in its box, from one end of the box to the other.

Answer with one JSON object and nothing else. It has one key, "order": a
list of the part names, each exactly once, exactly as they are named to
you. The first part goes at one end of the box and the last at the other.

Rules:
- If a constraint says two parts must be kept apart, put one first and the
  other last.
- A part that gets warm (it draws the most current) and a sensor that
  measures temperature go at opposite ends.
- Parts that have nothing said about them go in the middle.

You do not choose positions or sizes; only the order.

The parts and the constraints follow.
