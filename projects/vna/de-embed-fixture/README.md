# de-embed-fixture — Capture a fixture's S-params for later de-embedding

Companion to [`../de-embed-pdf/`](../de-embed-pdf/). Walks you through
capturing the fixture-alone .s2p (DUT replaced by a precision THRU)
that de-embed-pdf needs.

Under the hood: thin wrapper around `../sparams-pdf/`. Just a CLI
convenience that names the output `<label>_fixture.s2p` so you can
remember which run was the fixture cal.

## Usage

```bash
python de_embed_fixture.py --start 1 --stop 1000 \
    --label "PCB test fixture v3" --out-dir ~/cals/
# → ~/cals/PCB_test_fixture_v3_fixture.s2p
# → ~/cals/PCB_test_fixture_v3_fixture.pdf
```

Then later:

```bash
python ../de-embed-pdf/de_embed_pdf.py \
    --measurement my_DUT_in_fixture.s2p \
    --fixture ~/cals/PCB_test_fixture_v3_fixture.s2p \
    --label "real DUT after de-embed" \
    --output dut_alone.pdf
```

## Flags

Mostly the same as sparams-pdf:

- `--vna`, `--port`, `--host`
- `--start MHZ` / `--stop MHZ` / `--points` / `--average` (default 4)
- `--power DBM` (HP only)
- `--label TEXT` — used in filenames
- `--out-dir DIR`
- `--no-prompt` — skip the manual confirmations
