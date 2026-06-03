#!/bin/bash
# Install and test ET5406A+ driver on greybox
# Run this script on greybox: bash install_and_test_load_on_greybox.sh

set -e

echo "======================================================================"
echo "Installing ET5406A+ driver on greybox"
echo "======================================================================"

# Create temp directory for installation
TMPDIR="/tmp/rf-bench-yertai-install"
mkdir -p "$TMPDIR"
cd "$TMPDIR"

echo ""
echo "[1] Installing dependencies..."
pip3 install ET54 pyvisa pyvisa-py pyserial --break-system-packages --quiet
echo "  ✓ Dependencies installed"

echo ""
echo "[2] Copying driver files..."
# The driver files will be copied separately
# For now, we'll install directly from the source

echo ""
echo "[3] Installing rf-bench-drivers-yertai..."
# We need to create a minimal package structure here
cat > setup.py << 'SETUP_EOF'
from setuptools import setup, find_packages

setup(
    name="rf-bench-drivers-yertai",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "ET54>=0.1",
        "pyvisa>=1.15.0",
        "pyvisa-py>=0.8.0",
        "pyserial>=3.5",
    ],
)
SETUP_EOF

# Create package structure
mkdir -p rf_bench/yertai

# Copy driver files (these will be copied by the user)
# For now, create placeholder to show what's needed

cat > rf_bench/__init__.py << 'INIT_EOF'
"""rf_bench namespace package"""
__path__ = __import__('pkgutil').extend_path(__path__, __name__)
INIT_EOF

cat > rf_bench/yertai/__init__.py << 'YERTAI_INIT_EOF'
"""rf_bench.yertai — Yertai ET5406A+ programmable DC load driver"""

from .et5406a import ET5406A, ET5406AError

__all__ = ["ET5406A", "ET5406AError"]
YERTAI_INIT_EOF

echo ""
echo "======================================================================"
echo "Installation script created"
echo "======================================================================"
echo ""
echo "Next steps:"
echo "  1. Copy the driver source file to greybox:"
echo "     scp ~/Dropbox/build/rf-bench/drivers/yertai/rf_bench/yertai/et5406a.py 10.1.0.16:/tmp/rf-bench-yertai-install/rf_bench/yertai/"
echo ""
echo "  2. Install the package:"
echo "     cd /tmp/rf-bench-yertai-install && pip3 install -e . --break-system-packages"
echo ""
echo "  3. Copy and run the test script:"
echo "     python3 /tmp/test_load.py"
echo ""
