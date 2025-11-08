#!/bin/bash
# Test DeepSeek-R1 (Reasoning Model) for Timeloop Mapping Evolution
# DeepSeek-R1 has strong mathematical reasoning capabilities

set -e

echo "========================================"
echo "DeepSeek-R1 Timeloop Mapping Evolution"
echo "Testing Reasoning Model (10 iterations)"
echo "========================================"
echo ""

# Activate environment
source /root/miniconda3/etc/profile.d/conda.sh
conda activate openevolve_env

# Set environment variables
export TIMELOOP_DIR=/root/timeloop
export LD_LIBRARY_PATH=$TIMELOOP_DIR/lib:$LD_LIBRARY_PATH
export PATH=$TIMELOOP_DIR/bin:$PATH

# Set DeepSeek API Key
export OPENAI_API_KEY="sk-93281cd0a2ed493d8a3f0480540a5ece"

echo "🔧 Environment Setup:"
echo "  → Timeloop: $TIMELOOP_DIR"
echo "  → DeepSeek API: https://api.deepseek.com"
echo "  → Model: deepseek-reasoner"
echo ""

# Clean old outputs
echo "🗑️  Cleaning old DeepSeek outputs..."
rm -rf outputs/evolution/eyeriss_mapping_deepseek_r1
mkdir -p logs

echo ""
echo "🚀 Starting DeepSeek-R1 evolution (10 iterations)..."
echo "   Expected: Better mathematical reasoning than GLM-4.6"
echo "   Key strength: Native reasoning capabilities"
echo ""

python /root/openevolve/openevolve-run.py \
    src/algorithm.py \
    src/evaluator_v2.py \
    --config config/config_deepseek_r1.yaml \
    --iterations 10 \
    --output ./outputs/evolution/eyeriss_mapping_deepseek_r1 \
    2>&1 | tee logs/evolution_deepseek_r1_10iter.log

echo ""
echo "========================================"
echo "✅ DeepSeek-R1 evolution complete!"
echo "📊 Results: logs/evolution_deepseek_r1_10iter.log"
echo "========================================"
