"""
retry.py — Retry decorator for transient failures

Handles network glitches, instrument timeouts, and temporary errors.
"""

import time
import functools
from typing import Callable, Type, Tuple


class RetryError(Exception):
    """Raised when all retry attempts fail."""
    pass


def retry(
    attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    """
    Retry decorator for functions that may fail transiently.

    Args:
        attempts: Maximum number of attempts (default 3)
        delay: Initial delay between retries in seconds (default 1.0)
        backoff: Multiplier for delay after each attempt (default 2.0)
        exceptions: Tuple of exception types to catch and retry

    Example::

        from rf_bench.automation import retry

        @retry(attempts=3, delay=1.0, backoff=2.0)
        def measure_voltage(dmm):
            return dmm.read()

        # Will retry up to 3 times with delays of 1s, 2s, 4s
        voltage = measure_voltage(dmm)

    Raises:
        RetryError: If all attempts fail
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None

            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < attempts:
                        print(f"Attempt {attempt}/{attempts} failed: {e}. Retrying in {current_delay:.1f}s...")
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        print(f"Attempt {attempt}/{attempts} failed: {e}. No more retries.")

            # All attempts failed
            raise RetryError(
                f"Failed after {attempts} attempts. Last error: {last_exception}"
            ) from last_exception

        return wrapper
    return decorator
