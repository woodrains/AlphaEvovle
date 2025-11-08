#!/bin/bash
# OpenEvolve Evolution Run Script for Soter Timeloop Mapping Optimization
# This script sets up the complete environment and runs the evolution

set -e  # Exit on error

echo "========================================"
echo "Soter Timeloop Mapping Evolution"
echo "========================================"

# ==================== Environment Setup ====================

echo ""
echo "🔧 Setting up environment..."

# 1. Activate conda environment
echo "  → Activating openevolve_env conda environment..."
source /root/miniconda3/etc/profile.d/conda.sh
conda activate openevolve_env

# 2. Set Timeloop paths
echo "  → Setting Timeloop paths..."
export PATH=/root/Soter_v4/Soter_v4/timeloop-v2.0/bin:$PATH
export LD_LIBRARY_PATH=/root/Soter_v4/Soter_v4/timeloop-v2.0/lib:$LD_LIBRARY_PATH

# 3. Set GLM API key
echo "  → Setting GLM API key..."
export GLM_API_KEY="283fe07947104336948a068b2501e885.Jnb3Nou8WS0Fz7Yj"

# 4. Change to project directory
cd /root/evolve_1108/cc_1108

echo "✅ Environment setup complete"

# ==================== Verify Environment ====================

echo ""
echo "🔍 Verifying environment..."

# Check Python version
python_version=$(python --version)
echo "  → Python: $python_version"

# Check OpenEvolve installation
if python -c "import openevolve" 2>/dev/null; then
    echo "  → OpenEvolve: ✅ Installed"
else
    echo "  → OpenEvolve: ❌ Not found"
    exit 1
fi

# Check Timeloop availability
if command -v timeloop-model &> /dev/null; then
    echo "  → Timeloop: ✅ Available"
else
    echo "  → Timeloop: ❌ Not found"
    exit 1
fi

# Check API key
if [ -z "$GLM_API_KEY" ]; then
    echo "  → GLM API Key: ❌ Not set"
    exit 1
else
    echo "  → GLM API Key: ✅ Set"
fi

echo "✅ Environment verification complete"

# ==================== Parse Arguments ====================

# Default values
ITERATIONS=${1:-1}
LOG_LEVEL=${2:-INFO}

echo ""
echo "📋 Evolution Configuration:"
echo "  → Iterations: $ITERATIONS"
echo "  → Log level: $LOG_LEVEL"

# ==================== Clean Old Temporary Files ====================

echo ""
echo "🗑️  Cleaning old temporary files..."
rm -rf outputs/timeloop_temp/* 2>/dev/null || true
echo "✅ Cleanup complete"

# ==================== Run Evolution ====================

echo ""
echo "🚀 Starting OpenEvolve evolution..."
echo "========================================"
echo ""

# Run OpenEvolve with updated paths
python /root/openevolve/openevolve-run.py \
    /root/evolve_1108/cc_1108/src/initial_program.py \
    /root/evolve_1108/cc_1108/src/evaluator.py \
    --config /root/evolve_1108/cc_1108/config/config.yaml \
    --iterations $ITERATIONS \
    --log-level $LOG_LEVEL

echo ""
echo "========================================"
echo "✅ Evolution complete!"
echo "📊 Results saved to: outputs/evolution/"
echo "🗺️  Best mapping: outputs/mappings/generated_mapping.yaml"
echo "========================================"
