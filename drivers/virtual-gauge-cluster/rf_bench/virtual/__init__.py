"""rf_bench.virtual package — Virtual instrument drivers"""
from .gauge_cluster import VirtualGaugeCluster, VirtualGaugeClusterError

__all__ = ["VirtualGaugeCluster", "VirtualGaugeClusterError"]
