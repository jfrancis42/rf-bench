#!/usr/bin/env python3
"""
Relay-Switched Filter Bank Controller

Controls a relay-switched bandpass or low-pass filter bank via XL9535 I2C I/O
expander (Bus Pirate I2C master).  Each relay selects a different filter stage.

Runs standalone (switch to a specific band/relay) or as an importable module
for other rf-bench projects (transmitter-test, receiver-test) to automatically
switch filters as frequency changes.

Usage:
    python relay_filterbank.py --freq HZ [options]   # switch to filter for frequency
    python relay_filterbank.py --relay N [options]   # switch to specific relay directly
    python relay_filterbank.py --off [options]       # all relays off (bypass)
    python relay_filterbank.py --list [options]      # list all filters in config
    python relay_filterbank.py --ping [options]      # cycle through all relays, test

Options:
    --bp PORT          Bus Pirate port (default /dev/ttyUSB1)
    --addr ADDR        XL9535 I2C address in hex (default 0x20)
    --config FILE      Filter bank JSON config (default: hf-lpf-bank.json in script dir)
    --active-low       Relay board is active-LOW (default active-HIGH / ULN2803)
    --dwell MS         Dwell time per relay in ping mode (default 500)
    --quiet            Suppress status output (for scripted use)
"""

import argparse
import json
import os
import sys
import time

from rf_bench.buspirate import BusPirate
from rf_bench.relay import XL9535, XL9535Error

DEFAULT_BP      = "/dev/ttyUSB1"
DEFAULT_I2C_ADDR = 0x20
_SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG  = os.path.join(_SCRIPT_DIR, "hf-lpf-bank.json")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class FilterBankError(RuntimeError):
    """Raised on filter bank configuration or frequency range errors."""


# ---------------------------------------------------------------------------
# FilterBank class (importable module interface)
# ---------------------------------------------------------------------------

class FilterBank:
    """
    Relay-switched filter bank controller.

    Each entry in the config JSON maps a relay number to a frequency range.
    ``select_for_freq()`` finds the matching filter and closes that relay,
    opening all others.

    Parameters
    ----------
    bp : BusPirate
        Bus Pirate instance.  The caller is responsible for opening the port
        (``BusPirate(port)`` or ``with BusPirate(port) as bp:``).
        This class will call ``bp.set_pullups(True)`` and
        ``bp.i2c_configure()`` internally.
    config_file : str
        Path to a JSON filter bank config file.  Defaults to
        ``hf-lpf-bank.json`` in the same directory as this script.
    i2c_addr : int
        XL9535 I2C address, 0x20–0x27 (default 0x20).
    active_high : bool
        True (default) for ULN2803-based boards where a high output
        energizes the relay coil.  False for active-LOW boards.
    quiet : bool
        Suppress informational output when True.

    Usage
    -----
    Direct instantiation::

        with BusPirate("/dev/ttyUSB1") as bp:
            fb = FilterBank(bp, config_file="hf-lpf-bank.json")
            fb.select_for_freq(14_200_000)
            fb.close()

    Context manager (preferred — calls all_off + i2c_exit on exit)::

        with BusPirate("/dev/ttyUSB1") as bp:
            with FilterBank(bp, config_file="hf-lpf-bank.json") as fb:
                fb.select_for_freq(7_074_000)
                # ... measurement ...
    """

    def __init__(self, bp, config_file: str = DEFAULT_CONFIG,
                 i2c_addr: int = DEFAULT_I2C_ADDR,
                 active_high: bool = True, quiet: bool = False):
        self._bp = bp
        self._quiet = quiet
        self._config = self._load_config(config_file)
        self._filters = self._config["filters"]
        self._num_relays = len(self._filters)

        # Validate relay indices are 0..N-1
        relay_indices = sorted(f["relay"] for f in self._filters)
        expected = list(range(self._num_relays))
        if relay_indices != expected:
            raise FilterBankError(
                f"Filter relay indices are not a contiguous 0..{self._num_relays - 1} "
                f"sequence: got {relay_indices}"
            )

        # Choose XL9535 num_relays (must be 4, 8, or 16)
        if self._num_relays <= 4:
            xl_relays = 4
        elif self._num_relays <= 8:
            xl_relays = 8
        else:
            xl_relays = 16

        # Enter I2C mode and create XL9535 driver
        bp.set_pullups(True)
        bp.i2c_configure(speed_hz=100_000)
        self._xl = XL9535(bp, i2c_addr=i2c_addr,
                          active_high=active_high, num_relays=xl_relays)

        if not quiet:
            print(f"Filter bank: {self._config.get('name', 'unnamed')}  "
                  f"({self._num_relays} filters,  I2C 0x{i2c_addr:02X})")

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_config(path: str) -> dict:
        if not os.path.exists(path):
            raise FilterBankError(
                f"Config file not found: {path}"
            )
        with open(path) as fh:
            data = json.load(fh)
        required = {"filters"}
        missing = required - set(data.keys())
        if missing:
            raise FilterBankError(
                f"Config file missing required key(s): {missing}"
            )
        for i, f in enumerate(data["filters"]):
            for k in ("relay", "label", "f_low_hz", "f_high_hz"):
                if k not in f:
                    raise FilterBankError(
                        f"Filter entry {i} missing required key '{k}'"
                    )
        return data

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select_for_freq(self, freq_hz: float) -> dict:
        """
        Select the filter covering *freq_hz*.

        Finds the first filter entry where
        ``f_low_hz <= freq_hz < f_high_hz`` and closes that relay,
        opening all others.

        Parameters
        ----------
        freq_hz : float
            Frequency in Hz.

        Returns
        -------
        dict
            The matched filter config entry.

        Raises
        ------
        FilterBankError
            If no filter covers *freq_hz*, with a message listing the
            available ranges.
        """
        for f in self._filters:
            if f["f_low_hz"] <= freq_hz < f["f_high_hz"]:
                if not self._quiet:
                    print(f"  freq {_fmt_hz(freq_hz)} → relay {f['relay']}  "
                          f"({f['label']})")
                self._xl.close_only(f["relay"])
                return f

        # Build a helpful error listing all ranges
        ranges = "  \n".join(
            f"  relay {f['relay']:2d}: {f['label']:20s}  "
            f"{_fmt_hz(f['f_low_hz'])} – {_fmt_hz(f['f_high_hz'])}"
            for f in self._filters
        )
        raise FilterBankError(
            f"No filter covers {_fmt_hz(freq_hz)}.  Available ranges:\n{ranges}"
        )

    def select_relay(self, relay_num: int) -> None:
        """
        Close relay *relay_num* and open all others.

        Parameters
        ----------
        relay_num : int
            Relay index, 0 .. num_relays-1.

        Raises
        ------
        FilterBankError
            If *relay_num* is out of range.
        """
        if not (0 <= relay_num < self._num_relays):
            raise FilterBankError(
                f"relay_num {relay_num} out of range [0, {self._num_relays - 1}]"
            )
        f = next((x for x in self._filters if x["relay"] == relay_num), None)
        if not self._quiet:
            label = f["label"] if f else "?"
            print(f"  relay {relay_num}  ({label})")
        self._xl.close_only(relay_num)

    def all_off(self) -> None:
        """De-energize all relays (bypass / no filter)."""
        self._xl.all_off()
        if not self._quiet:
            print("  all relays off (bypass)")

    def get_filters(self) -> list:
        """Return a copy of the filter config list."""
        return list(self._filters)

    def get_name(self) -> str:
        """Return the filter bank name from the config."""
        return self._config.get("name", "unnamed")

    def close(self) -> None:
        """De-energize all relays and exit I2C mode."""
        self._xl.all_off()
        try:
            self._bp.i2c_exit()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_hz(hz: float) -> str:
    """Format a frequency in Hz as kHz or MHz string."""
    if hz == 0:
        return "DC"
    mhz = hz / 1_000_000
    if mhz >= 1.0:
        return f"{mhz:.3f} MHz"
    return f"{hz / 1_000:.1f} kHz"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_list(fb: FilterBank) -> None:
    """Print the filter list in a table."""
    name = fb.get_name()
    filters = fb.get_filters()
    print(f"\nFilter bank: {name}")
    print(f"{'Relay':>6}  {'Label':<22}  {'Low':>12}  {'High':>12}")
    print("-" * 62)
    for f in sorted(filters, key=lambda x: x["relay"]):
        lo = _fmt_hz(f["f_low_hz"])
        hi = _fmt_hz(f["f_high_hz"])
        print(f"  {f['relay']:4d}  {f['label']:<22}  {lo:>12}  {hi:>12}")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Relay-switched filter bank controller",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    # Mutually exclusive actions
    action = ap.add_mutually_exclusive_group(required=True)
    action.add_argument("--freq", type=float, metavar="HZ",
                        help="Switch to filter covering this frequency (Hz)")
    action.add_argument("--relay", type=int, metavar="N",
                        help="Switch to relay N directly")
    action.add_argument("--off", action="store_true",
                        help="De-energize all relays (bypass)")
    action.add_argument("--list", action="store_true",
                        help="List all filters in config and exit")
    action.add_argument("--ping", action="store_true",
                        help="Cycle through all relays (hardware test)")

    ap.add_argument("--bp",        default=DEFAULT_BP, metavar="PORT",
                    help=f"Bus Pirate port (default {DEFAULT_BP})")
    ap.add_argument("--addr",      default="0x20", metavar="ADDR",
                    help="XL9535 I2C address in hex (default 0x20)")
    ap.add_argument("--config",    default=DEFAULT_CONFIG, metavar="FILE",
                    help="Filter bank JSON config (default: hf-lpf-bank.json)")
    ap.add_argument("--active-low", action="store_true",
                    help="Relay board is active-LOW (default: active-HIGH/ULN2803)")
    ap.add_argument("--dwell",     type=int, default=500, metavar="MS",
                    help="Dwell per relay in ping mode, ms (default 500)")
    ap.add_argument("--quiet",     action="store_true",
                    help="Suppress status output")
    args = ap.parse_args()

    try:
        i2c_addr = int(args.addr, 0)
    except ValueError:
        ap.error(f"Invalid I2C address: {args.addr!r}  (use hex like 0x20)")

    active_high = not args.active_low

    # --list: load config without opening hardware
    if args.list:
        config_path = args.config
        if not os.path.exists(config_path):
            print(f"Error: config file not found: {config_path}", file=sys.stderr)
            sys.exit(1)
        with open(config_path) as fh:
            config = json.load(fh)
        name = config.get("name", "unnamed")
        filters = config.get("filters", [])
        print(f"\nFilter bank: {name}")
        print(f"{'Relay':>6}  {'Label':<22}  {'Low':>12}  {'High':>12}")
        print("-" * 62)
        for f in sorted(filters, key=lambda x: x["relay"]):
            lo = _fmt_hz(f["f_low_hz"])
            hi = _fmt_hz(f["f_high_hz"])
            print(f"  {f['relay']:4d}  {f['label']:<22}  {lo:>12}  {hi:>12}")
        print()
        return

    # All other actions need hardware
    with BusPirate(args.bp) as bp:
        with FilterBank(bp, config_file=args.config,
                        i2c_addr=i2c_addr, active_high=active_high,
                        quiet=args.quiet) as fb:

            if args.freq is not None:
                try:
                    matched = fb.select_for_freq(args.freq)
                    if not args.quiet:
                        print(f"Selected: relay {matched['relay']}  "
                              f"{matched['label']}")
                except FilterBankError as exc:
                    print(f"Error: {exc}", file=sys.stderr)
                    sys.exit(1)

            elif args.relay is not None:
                try:
                    fb.select_relay(args.relay)
                    if not args.quiet:
                        print(f"Selected: relay {args.relay}")
                except FilterBankError as exc:
                    print(f"Error: {exc}", file=sys.stderr)
                    sys.exit(1)

            elif args.off:
                fb.all_off()

            elif args.ping:
                filters = sorted(fb.get_filters(), key=lambda x: x["relay"])
                print(f"Ping: cycling {len(filters)} relays  "
                      f"(dwell {args.dwell} ms each)")
                for f in filters:
                    print(f"  relay {f['relay']:2d}  {f['label']}")
                    fb.select_relay(f["relay"])
                    time.sleep(args.dwell / 1000.0)
                fb.all_off()
                print("Ping complete.")


if __name__ == "__main__":
    main()
