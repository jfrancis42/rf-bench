#!/usr/bin/env python3
"""
portable_rf_survey.py — Sweep many cables in a session, generate a
combined HTML report.

For an installation visit where you want to characterise every
patch lead / antenna / feedline in the room, this iterates a list
of DUTs (taken from a YAML config), runs swr-pdf on each, and
generates a single HTML index linking to all the PDFs.

The config file format:

  start_mhz: 1.0
  stop_mhz:  500.0
  duts:
    - label: "100 ft RG-58 attic feed"
    - label: "20 ft RG-58 patch"
    - label: "PL-259 jumper #3"
    - label: "diplexer common port"

The script prompts you between each DUT ("connect DUT X, press
Enter") so an operator can walk the rack and capture everything
without retyping CLI commands for each.
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore", message="Unable to import Axes3D")
import argparse, json, sys, subprocess
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(
        description="Batch many DUT sweeps + HTML index.")
    p.add_argument("--config", required=True, metavar="FILE.json",
                   help="JSON config (see project README for schema)")
    p.add_argument("--out-dir", default=".")
    p.add_argument("--vna", choices=("nanovna","hp"), default="nanovna")
    p.add_argument("--port", default="/dev/ttyACM1")
    p.add_argument("--host", default="10.1.1.70")
    p.add_argument("--no-prompt", action="store_true")
    args = p.parse_args()
    cfg_path = Path(args.config)
    cfg = json.loads(cfg_path.read_text())
    start = cfg["start_mhz"]; stop = cfg["stop_mhz"]
    duts = cfg["duts"]
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    swr_pdf = (Path(__file__).resolve().parent.parent /
               "swr-pdf" / "swr_pdf.py")

    entries = []
    for i, dut in enumerate(duts, 1):
        label = dut["label"]
        safe = label.replace(" ","_").replace("/","_")
        pdf_path = out_dir / f"{ts}_dut{i:02d}_{safe}.pdf"
        if not args.no_prompt:
            try: input(f"\nDUT {i}/{len(duts)}: connect '{label}', press Enter…")
            except EOFError: pass
        cmd = [sys.executable, str(swr_pdf),
               "--vna", args.vna, "--port", args.port, "--host", args.host,
               "--start", str(start), "--stop", str(stop),
               "--label", label, "--output", str(pdf_path)]
        rc = subprocess.call(cmd)
        entries.append({"label": label, "pdf": pdf_path.name, "rc": rc})

    # HTML index
    html_path = out_dir / f"{ts}_survey.html"
    with html_path.open("w") as fh:
        fh.write("<!doctype html><html><head><meta charset='utf-8'>"
                 "<title>RF survey</title>"
                 "<style>body{font-family:sans-serif;max-width:800px;margin:auto;padding:1em}"
                 "table{border-collapse:collapse;width:100%}"
                 "td,th{padding:.4em;border-bottom:1px solid #ccc}</style>"
                 "</head><body>")
        fh.write(f"<h1>RF survey — {ts}</h1>")
        fh.write(f"<p>Sweep {start} – {stop} MHz. {len(entries)} DUTs.</p>")
        fh.write("<table><tr><th>#</th><th>DUT</th><th>PDF</th><th>RC</th></tr>")
        for i, e in enumerate(entries, 1):
            fh.write(f"<tr><td>{i}</td><td>{e['label']}</td>"
                     f"<td><a href='{e['pdf']}'>{e['pdf']}</a></td>"
                     f"<td>{e['rc']}</td></tr>")
        fh.write("</table></body></html>")
    print(f"\nWrote survey index: {html_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
