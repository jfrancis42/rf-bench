#!/usr/bin/env python3
"""
Relay Normalizer — 2-relay reference/DUT path switcher for measurement normalization.

Automates the most common manual step in scalar RF measurements: switching between a
"reference through" path (source → detector directly) and the "DUT" path (source →
DUT → detector) without touching cables.

Usage:
    python relay_normalize.py --ref             # switch to reference path
    python relay_normalize.py --dut             # switch to DUT path
    python relay_normalize.py --off             # open both relays (safe state)
    python relay_normalize.py --status          # show current path
    python relay_normalize.py --cycle N         # cycle ref/dut N times (self-test)
    python relay_normalize.py --measure         # interactive: prompt ref then DUT

Options:
    --bp PORT          Bus Pirate port (default /dev/ttyUSB1)
    --addr ADDR        XL9535 I2C address, hex OK (default 0x20)
    --ref-relay N      Relay number for reference path (default 0)
    --dut-relay N      Relay number for DUT path (default 1)
    --active-low       Relay board is active-LOW (default: active-HIGH)
    --settle-ms MS     Settle delay after relay switch, milliseconds (default 50)
    --quiet            Suppress informational output

As an importable library:

    from rf_bench.buspirate import BusPirate
    from relay_normalize import PathSwitcher

    with BusPirate("/dev/ttyUSB1") as bp:
        with PathSwitcher(bp) as ps:
            ps.select_reference()
            ref_data = measure()
            ps.select_dut()
            dut_data = measure()
            normalized = dut_data / ref_data
"""

import argparse
import time

DEFAULT_BP        = "/dev/ttyUSB1"
DEFAULT_ADDR      = 0x20
DEFAULT_REF_RELAY = 0
DEFAULT_DUT_RELAY = 1
DEFAULT_SETTLE_MS = 50
MEASURE_PAUSE_S   = 2.0   # hold after Enter in --measure mode


# ---------------------------------------------------------------------------
# PathSwitcher — importable library class
# ---------------------------------------------------------------------------

class PathSwitcher:
    """
    2-relay reference/DUT path switcher for measurement normalization.

    Wraps an XL9535 relay board so that a caller can switch between a
    "reference through" path and a "DUT" path with a single method call.

    The two relays are mutually exclusive (close_only semantics): switching to
    one path always de-energizes the other before energizing the new one.

    Parameters
    ----------
    bp : BusPirate
        Bus Pirate instance.  I2C mode is entered by PathSwitcher.__init__ and
        exited by PathSwitcher.close() / __exit__.
    ref_relay : int
        Relay number for the reference (bypass) path (default 0).
    dut_relay : int
        Relay number for the DUT path (default 1).
    i2c_addr : int
        7-bit I2C address of the XL9535 (default 0x20).
    active_high : bool
        True for ULN2803-based active-HIGH boards (default).
        False for active-LOW (direct NPN driver) boards.
    settle_ms : int
        Milliseconds to wait after a relay switch before returning.  Allows
        relay contact bounce to settle and downstream instruments to stabilize.

    Usage
    -----
    ::

        with PathSwitcher(bp, settle_ms=50) as ps:
            ps.select_reference()
            ref = measure()
            ps.select_dut()
            dut = measure()
            ps.all_off()
        # I2C mode exited, relays de-energized

    Integration pattern for other scripts
    --------------------------------------
    ::

        def run_with_normalization(ps, measure_fn):
            ps.select_reference()
            ref = measure_fn()
            ps.select_dut()
            dut = measure_fn()
            ps.all_off()
            return ref, dut
    """

    def __init__(self, bp, ref_relay: int = DEFAULT_REF_RELAY,
                 dut_relay: int = DEFAULT_DUT_RELAY,
                 i2c_addr: int = DEFAULT_ADDR,
                 active_high: bool = True,
                 settle_ms: int = DEFAULT_SETTLE_MS):
        from rf_bench.relay import XL9535

        self._bp          = bp
        self._ref_relay   = ref_relay
        self._dut_relay   = dut_relay
        self._settle_ms   = settle_ms
        self._active_path = None   # None | "ref" | "dut" | "off"

        bp.set_pullups(True)
        bp.i2c_configure(speed_hz=100_000)
        self._rl = XL9535(bp, i2c_addr=i2c_addr,
                          active_high=active_high,
                          num_relays=max(ref_relay, dut_relay) + 1
                          if max(ref_relay, dut_relay) < 4
                          else (8 if max(ref_relay, dut_relay) < 8 else 16))
        # __init__ calls configure_outputs() + all_off() internally
        self._active_path = "off"

    def _settle(self) -> None:
        if self._settle_ms > 0:
            time.sleep(self._settle_ms / 1000.0)

    def select_reference(self) -> None:
        """Switch to the reference (bypass) path and wait settle_ms."""
        self._rl.close_only(self._ref_relay)
        self._active_path = "ref"
        self._settle()

    def select_dut(self) -> None:
        """Switch to the DUT path and wait settle_ms."""
        self._rl.close_only(self._dut_relay)
        self._active_path = "dut"
        self._settle()

    def all_off(self) -> None:
        """De-energize both relays (safe state)."""
        self._rl.all_off()
        self._active_path = "off"

    @property
    def active_path(self):
        """Current path: 'ref', 'dut', 'off', or None (not yet initialized)."""
        return self._active_path

    def close(self) -> None:
        """De-energize relays and exit I2C mode.  Called by __exit__."""
        self.all_off()
        try:
            self._bp.i2c_exit()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _parse_addr(s: str) -> int:
    """Accept '0x20', '32', '0X20' as I2C address."""
    return int(s, 0)


def _status_str(path) -> str:
    labels = {"ref": "REFERENCE (bypass)", "dut": "DUT", "off": "OFF (both open)"}
    return labels.get(path, "UNKNOWN")


# ---------------------------------------------------------------------------
# --measure interactive mode
# ---------------------------------------------------------------------------

def _run_measure(ps: PathSwitcher, quiet: bool) -> None:
    """Interactive guided measurement: reference then DUT."""
    if not quiet:
        print("--- Guided measurement mode ---")
        print("This mode walks you through capturing a reference measurement,")
        print("then a DUT measurement on your external instruments.\n")

    # --- Reference ---
    if not quiet:
        print("Switching to REFERENCE path...")
    ps.select_reference()
    if not quiet:
        print("  Reference path active (relay energized, bypass connected).")
        input("  Press Enter when ready to capture reference...")
        print(f"  Waiting {MEASURE_PAUSE_S:.0f} s for instrument settle...", end="", flush=True)
    time.sleep(MEASURE_PAUSE_S)
    if not quiet:
        print(" done.")
        print("  Reference path active. Capture your reference measurement now.\n")

    # --- DUT ---
    if not quiet:
        print("Switching to DUT path...")
    ps.select_dut()
    if not quiet:
        print("  DUT path active (relay energized, DUT inserted).")
        input("  Press Enter when ready to capture DUT measurement...")
        print(f"  Waiting {MEASURE_PAUSE_S:.0f} s for instrument settle...", end="", flush=True)
    time.sleep(MEASURE_PAUSE_S)
    if not quiet:
        print(" done.")
        print("  DUT path active. Capture your DUT measurement now.\n")
        print("Both measurements complete. Switch back to --ref or --dut as needed.")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="2-relay reference/DUT path switcher for measurement normalization."
    )

    # Action group — exactly one required
    action = ap.add_mutually_exclusive_group(required=True)
    action.add_argument("--ref",    action="store_true", help="Switch to reference path")
    action.add_argument("--dut",    action="store_true", help="Switch to DUT path")
    action.add_argument("--off",    action="store_true", help="Open both relays (safe state)")
    action.add_argument("--status", action="store_true", help="Show current path")
    action.add_argument("--cycle",  type=int, metavar="N",
                        help="Cycle ref/dut N times (self-test)")
    action.add_argument("--measure", action="store_true",
                        help="Interactive: guided ref then DUT capture")

    # Hardware options
    ap.add_argument("--bp",        default=DEFAULT_BP, metavar="PORT",
                    help=f"Bus Pirate port (default {DEFAULT_BP})")
    ap.add_argument("--addr",      default=hex(DEFAULT_ADDR), metavar="ADDR",
                    type=_parse_addr,
                    help=f"XL9535 I2C address (default 0x{DEFAULT_ADDR:02X})")
    ap.add_argument("--ref-relay", default=DEFAULT_REF_RELAY, type=int, metavar="N",
                    help=f"Relay number for reference path (default {DEFAULT_REF_RELAY})")
    ap.add_argument("--dut-relay", default=DEFAULT_DUT_RELAY, type=int, metavar="N",
                    help=f"Relay number for DUT path (default {DEFAULT_DUT_RELAY})")
    ap.add_argument("--active-low", action="store_true",
                    help="Relay board is active-LOW (default: active-HIGH)")
    ap.add_argument("--settle-ms", default=DEFAULT_SETTLE_MS, type=int, metavar="MS",
                    help=f"Settle delay after relay switch in ms (default {DEFAULT_SETTLE_MS})")
    ap.add_argument("--quiet",     action="store_true", help="Suppress informational output")

    args = ap.parse_args()

    from rf_bench.buspirate import BusPirate

    with BusPirate(args.bp) as bp:
        ps = PathSwitcher(
            bp,
            ref_relay   = args.ref_relay,
            dut_relay   = args.dut_relay,
            i2c_addr    = args.addr,
            active_high = not args.active_low,
            settle_ms   = args.settle_ms,
        )
        try:
            if args.ref:
                ps.select_reference()
                if not args.quiet:
                    print(f"REFERENCE path active (relay {args.ref_relay}).")

            elif args.dut:
                ps.select_dut()
                if not args.quiet:
                    print(f"DUT path active (relay {args.dut_relay}).")

            elif args.off:
                ps.all_off()
                if not args.quiet:
                    print("Both relays open (safe state).")

            elif args.status:
                print(f"Active path: {_status_str(ps.active_path)}")

            elif args.cycle is not None:
                if not args.quiet:
                    print(f"Cycling ref/dut {args.cycle} times "
                          f"(settle {args.settle_ms} ms)...")
                for i in range(args.cycle):
                    ps.select_reference()
                    if not args.quiet:
                        print(f"  [{i+1}/{args.cycle}] REF")
                    ps.select_dut()
                    if not args.quiet:
                        print(f"  [{i+1}/{args.cycle}] DUT")
                ps.all_off()
                if not args.quiet:
                    print("Cycle complete.  Both relays open.")

            elif args.measure:
                _run_measure(ps, args.quiet)

        finally:
            # Leave relays in whatever state the action left them.
            # PathSwitcher.close() will call all_off(); that happens via context
            # manager on BusPirate exit.  Explicit close here for clarity.
            ps.close()


if __name__ == "__main__":
    main()
