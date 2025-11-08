#!/bin/bash
# Test improved prompts with 10 iterations

set -e

echo "========================================"
echo "Testing Improved Prompts (MLX-style)"
echo "10 Iteration Validation Run"
echo "========================================"
echo ""

# Activate environment
source /root/miniconda3/etc/profile.d/conda.sh
conda activate openevolve_env

# Set environment variables
export TIMELOOP_DIR=/root/timeloop
export LD_LIBRARY_PATH=$TIMELOOP_DIR/lib:$LD_LIBRARY_PATH
export PATH=$TIMELOOP_DIR/bin:$PATH
export GLM_API_KEY="d14b2d73bce15e34f19d1eb7e3fc1cd8.SczgGOlX1c0s19vU"

# Clean old outputs
echo "🗑️  Cleaning old outputs for fresh start..."
rm -rf outputs/evolution/eyeriss_mapping_v2_evolution_improved
rm -rf src/openevolve_output_improved
mkdir -p logs

# Run evolution with improved prompts
echo ""
echo "🚀 Starting evolution with IMPROVED PROMPTS (10 iterations)..."
echo "   Expected: Higher success rate on dimension budget conservation"
echo ""

python /root/openevolve/openevolve-run.py \
    src/algorithm.py \
    src/evaluator_v2.py \
    --config config/config_v2.yaml \
    --iterations 10 \
    --output ./outputs/evolution/eyeriss_mapping_v2_evolution_improved \
    2>&1 | tee logs/evolution_improved_prompts_10iter.log

echo ""
echo "========================================"
echo "✅ Validation complete!"
echo "📊 Results in: logs/evolution_improved_prompts_10iter.log"
echo "========================================"
