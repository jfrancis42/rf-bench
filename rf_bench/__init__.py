"""rf-bench: Python drivers and automation for RF test equipment.

Quick start:
    from rf_bench import connect

    sdg = connect('sdg')
    ssa = connect('ssa-main')

Or direct driver import:
    from rf_bench.siglent import SSA3000X

    ssa = SSA3000X("10.1.1.60")
"""

from .inventory import connect

__version__ = "0.2.0"
__all__ = ['connect']
