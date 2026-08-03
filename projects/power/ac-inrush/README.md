# AC Inrush Current Capture

Fluke 80i-400 clamp + SDS2000X scope. Captures the turn-on inrush surge of a
mains device (transformer, motor, PSU) and reports peak current, duration above
10 % of peak, and I²t (A²·s). Non-invasive AC-mains complement to
`../inrush/` (which measures DC inrush across a sense resistor).

**Current-only, so safe** — inrush is characterized entirely by the current
transient. No voltage sensing, no mains-voltage contact.

## Connections

```
conductor ──► 80i-400 clamp ──► burden resistor (1 Ω) ──► scope CH1
```

## Procedure

1. Clamp the **de-energized** supply conductor, connect burden → scope.
2. Run the script — it arms a capture over `--window` seconds.
3. Energize the device during that window. The transient is captured and
   analyzed.

```bash
python ac_inrush.py                    # CH1, 1 Ω, 200 ms window
python ac_inrush.py --window 0.5       # 500 ms
python ac_inrush.py --vdiv 2.0         # pin V/div — inrush can be 10× steady;
                                       # auto-range may clip the surge
python ac_inrush.py --plot inrush.png
```

Reports peak inrush (A), time to peak, duration >10 % of peak, I²t (A²·s),
steady-state RMS, and inrush ratio. `--plot` saves current-vs-time.

**Tip:** because inrush is a one-shot, pin `--vdiv` from a known-safe estimate
rather than trusting auto-range on the first energization.

See `ideas/fluke-80i400-projects.md`.
