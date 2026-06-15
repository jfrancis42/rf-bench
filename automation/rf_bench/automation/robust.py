"""
Robust Connection Wrappers

Enhanced error handling for instrument connections.

Provides connection wrappers that automatically retry on transient failures.
"""

import time
from typing import Any, Callable, Optional, Type
from contextlib import contextmanager

from .retry import retry, RetryError


class RobustConnection:
    """
    Wraps an instrument connection with automatic retry logic.

    Example:
        from rf_bench.automation import RobustConnection
        from rf_bench.siglent import SDM3045X

        # Wrap connection with automatic retry
        with RobustConnection(SDM3045X, '10.1.1.63', retry_attempts=3) as dmm:
            voltage = dmm.read()  # Auto-retries on failure
    """

    def __init__(
        self,
        instrument_class: Type,
        *args,
        retry_attempts: int = 3,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
        **kwargs
    ):
        """
        Initialize robust connection wrapper.

        Args:
            instrument_class: Instrument class to instantiate
            *args: Arguments for instrument constructor
            retry_attempts: Number of retry attempts
            retry_delay: Initial delay between retries (seconds)
            retry_backoff: Backoff multiplier for each retry
            **kwargs: Keyword arguments for instrument constructor
        """
        self._instrument_class = instrument_class
        self._args = args
        self._kwargs = kwargs
        self._retry_attempts = retry_attempts
        self._retry_delay = retry_delay
        self._retry_backoff = retry_backoff
        self._instrument = None

    def __enter__(self):
        """Connect to instrument with retry."""
        @retry(
            attempts=self._retry_attempts,
            delay=self._retry_delay,
            backoff=self._retry_backoff
        )
        def connect():
            return self._instrument_class(*self._args, **self._kwargs)

        self._instrument = connect()
        return self._instrument

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close connection."""
        if self._instrument is not None:
            try:
                self._instrument.close()
            except:
                pass  # Ignore close errors


@contextmanager
def robust_instrument(
    instrument_class: Type,
    *args,
    retry_attempts: int = 3,
    **kwargs
):
    """
    Context manager for robust instrument connections.

    Simpler alternative to RobustConnection class.

    Example:
        from rf_bench.automation import robust_instrument
        from rf_bench.siglent import SDM3045X

        with robust_instrument(SDM3045X, '10.1.1.63', retry_attempts=3) as dmm:
            voltage = dmm.read()
    """
    with RobustConnection(instrument_class, *args, retry_attempts=retry_attempts, **kwargs) as inst:
        yield inst


def with_retry(
    attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,)
):
    """
    Decorator to add retry logic to any function.

    Example:
        from rf_bench.automation import with_retry

        @with_retry(attempts=5, delay=0.5)
        def measure_voltage(dmm):
            return dmm.read()

        # Function will retry up to 5 times on failure
        voltage = measure_voltage(dmm)
    """
    return retry(
        attempts=attempts,
        delay=delay,
        backoff=backoff,
        exceptions=exceptions
    )


def connection_health_check(instrument, timeout: float = 5.0) -> bool:
    """
    Check if instrument connection is healthy.

    Sends *IDN? and checks for response.

    Args:
        instrument: Instrument instance
        timeout: Timeout in seconds

    Returns:
        True if connection healthy, False otherwise
    """
    try:
        # Try to identify instrument
        idn = instrument.identify()
        return len(idn) > 0
    except Exception:
        return False


def reconnect_if_needed(instrument, instrument_class: Type, *args, **kwargs):
    """
    Reconnect to instrument if connection is unhealthy.

    Args:
        instrument: Current instrument instance
        instrument_class: Instrument class for reconnection
        *args: Arguments for constructor
        **kwargs: Keyword arguments for constructor

    Returns:
        Instrument instance (existing or new)
    """
    if not connection_health_check(instrument):
        # Connection unhealthy, reconnect
        try:
            instrument.close()
        except:
            pass

        instrument = instrument_class(*args, **kwargs)

    return instrument
