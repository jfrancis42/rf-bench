"""Contour Design ShuttleXpress driver via Linux evdev.

The ShuttleXpress has three control types:
  - Jog wheel (center, free-spinning): relative encoder, one tick per detent
  - Shuttle ring (outer, spring-return): absolute position -7 to +7, center = 0
  - Buttons (5): momentary press/release

The Linux kernel HID driver reports:
  - Jog: EV_REL / REL_DIAL, value = +1 or -1 per detent
  - Shuttle: EV_REL / REL_WHEEL, value = absolute position (-7..+7)
  - Buttons: EV_KEY / BTN_0..BTN_4, value = 1 (press) or 0 (release)
"""

import asyncio
import enum
import selectors
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import evdev
from evdev import ecodes


VENDOR_ID = 0x0B33
PRODUCT_ID = 0x0020
DEVICE_NAME = "Contour Design ShuttleXpress"

REL_DIAL = ecodes.REL_DIAL        # 7 — jog wheel
REL_WHEEL = ecodes.REL_WHEEL      # 8 — shuttle ring position


class EventType(enum.Enum):
    JOG = "jog"
    SHUTTLE = "shuttle"
    BUTTON_PRESS = "button_press"
    BUTTON_RELEASE = "button_release"


@dataclass(frozen=True, slots=True)
class ShuttleEvent:
    type: EventType
    value: int
    timestamp: float


class ShuttleXpress:
    """Driver for the Contour Design ShuttleXpress USB jog/shuttle controller.

    Usage:
        shuttle = ShuttleXpress()

        @shuttle.on_jog
        def handle_jog(event):
            print(f"Jog: {event.value}")  # +1 or -1

        @shuttle.on_shuttle
        def handle_shuttle(event):
            print(f"Shuttle: {event.value}")  # -7 to +7

        @shuttle.on_button
        def handle_button(event):
            print(f"Button {event.value}: {event.type}")

        shuttle.run()  # blocks; Ctrl-C to stop
    """

    def __init__(self, device_path: Optional[str] = None):
        self._device = self._open_device(device_path)
        self._jog_callbacks: list[Callable] = []
        self._shuttle_callbacks: list[Callable] = []
        self._button_callbacks: list[Callable] = []
        self._any_callbacks: list[Callable] = []
        self._shuttle_position = 0
        self._running = False

    @staticmethod
    def _open_device(path: Optional[str] = None) -> evdev.InputDevice:
        if path:
            return evdev.InputDevice(path)
        for p in evdev.list_devices():
            dev = evdev.InputDevice(p)
            if dev.info.vendor == VENDOR_ID and dev.info.product == PRODUCT_ID:
                return dev
            dev.close()
        raise FileNotFoundError(
            f"ShuttleXpress not found. Check USB connection and "
            f"ensure user is in the 'input' group."
        )

    @staticmethod
    def find() -> Optional[str]:
        """Return the device path if a ShuttleXpress is connected, else None."""
        for p in evdev.list_devices():
            dev = evdev.InputDevice(p)
            if dev.info.vendor == VENDOR_ID and dev.info.product == PRODUCT_ID:
                path = dev.path
                dev.close()
                return path
            dev.close()
        return None

    @property
    def path(self) -> str:
        return self._device.path

    @property
    def shuttle_position(self) -> int:
        """Current shuttle ring position (-7 to +7)."""
        return self._shuttle_position

    def on_jog(self, fn: Callable) -> Callable:
        """Decorator: register a jog wheel callback. Receives ShuttleEvent with value +1/-1."""
        self._jog_callbacks.append(fn)
        return fn

    def on_shuttle(self, fn: Callable) -> Callable:
        """Decorator: register a shuttle ring callback. Receives ShuttleEvent with value -7..+7."""
        self._shuttle_callbacks.append(fn)
        return fn

    def on_button(self, fn: Callable) -> Callable:
        """Decorator: register a button callback. Receives ShuttleEvent with value = button number (1-5)."""
        self._button_callbacks.append(fn)
        return fn

    def on_any(self, fn: Callable) -> Callable:
        """Decorator: register a callback for all events."""
        self._any_callbacks.append(fn)
        return fn

    def _dispatch(self, event: ShuttleEvent):
        for fn in self._any_callbacks:
            fn(event)
        if event.type == EventType.JOG:
            for fn in self._jog_callbacks:
                fn(event)
        elif event.type == EventType.SHUTTLE:
            for fn in self._shuttle_callbacks:
                fn(event)
        elif event.type in (EventType.BUTTON_PRESS, EventType.BUTTON_RELEASE):
            for fn in self._button_callbacks:
                fn(event)

    def _process_evdev_event(self, ev):
        ts = ev.timestamp()

        if ev.type == ecodes.EV_REL:
            if ev.code == REL_DIAL:
                self._dispatch(ShuttleEvent(EventType.JOG, ev.value, ts))
            elif ev.code == REL_WHEEL:
                self._shuttle_position = ev.value
                self._dispatch(ShuttleEvent(EventType.SHUTTLE, ev.value, ts))

        elif ev.type == ecodes.EV_KEY:
            btn_num = ev.code - ecodes.BTN_0 + 1  # 1-indexed
            if 1 <= btn_num <= 5:
                etype = EventType.BUTTON_PRESS if ev.value else EventType.BUTTON_RELEASE
                self._dispatch(ShuttleEvent(etype, btn_num, ts))

    def run(self):
        """Blocking event loop. Ctrl-C to stop."""
        self._running = True
        try:
            for ev in self._device.read_loop():
                if not self._running:
                    break
                self._process_evdev_event(ev)
        except KeyboardInterrupt:
            pass
        finally:
            self._running = False

    def stop(self):
        """Signal the event loop to stop."""
        self._running = False

    def run_in_thread(self) -> threading.Thread:
        """Start the event loop in a daemon thread. Returns the thread."""
        t = threading.Thread(target=self.run, daemon=True)
        t.start()
        return t

    async def run_async(self):
        """Async event loop using evdev's async API."""
        self._running = True
        try:
            async for ev in self._device.async_read_loop():
                if not self._running:
                    break
                self._process_evdev_event(ev)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False

    def close(self):
        """Stop and close the device."""
        self.stop()
        self._device.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __repr__(self):
        return f"ShuttleXpress({self._device.path!r})"
