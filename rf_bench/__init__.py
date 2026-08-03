"""rf-bench: Python drivers and automation for RF test equipment.

Quick start:
    from rf_bench import connect

    sdg = connect('sdg')
    ssa = connect('ssa-main')

Or direct driver import:
    from rf_bench.siglent import SSA3000X

    ssa = SSA3000X("10.1.1.60")
"""

# `rf_bench` is a regular package here (it owns the inventory helper), but every
# driver package ships `rf_bench.<name>` as a PEP 420 namespace portion. Without
# this line, installing rf-bench would shadow all of them and
# `from rf_bench.siglent import ...` would stop resolving. extend_path merges
# the namespace portions found elsewhere on sys.path into this package's path.
__path__ = __import__('pkgutil').extend_path(__path__, __name__)

from .inventory import connect

__version__ = "0.2.0"
__all__ = ['connect']
