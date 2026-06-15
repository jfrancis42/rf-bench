"""rf-bench instrument inventory system.

Provides centralized connection management for all instruments.

Usage:
    from rf_bench import connect

    sdg = connect('sdg')
    ssa = connect('ssa-main')

Or explicit inventory management:
    from rf_bench.inventory import Inventory

    inv = Inventory()
    sdg = inv.connect('sdg')
    info = inv.get('ssa-main')
"""

from .manager import Inventory, connect

__all__ = ['Inventory', 'connect']
