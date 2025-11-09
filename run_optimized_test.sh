#!/bin/bash
# Optimized Evolution Test Script with All Fixes
# Based on AlphaTuner success patterns and critical bug fixes

cd /root/evolve_1108/cc_1108

# Activate conda environment
source /root/miniconda3/etc/profile.d/conda.sh
conda activate rtl_pilot

# Set OpenAI API key for DeepSeek
export OPENAI_API_KEY="sk-93281cd0a2ed493d8a3f0480540a5ece"

# Clean start - remove old database
echo "🧹 Cleaning old database..."
rm -rf ./outputs/evolution/eyeriss_CLEAN_START

# Create output directories
mkdir -p logs
mkdir -p outputs/mappings

echo "🚀 Starting Optimized Evolution Test"
echo "================================"
echo "Key Optimizations Applied:"
echo "  ✓ Fixed parallel evaluation file race (unique per-program directories)"
echo "  ✓ Custom prompts emphasizing numeric parameter mutations"
echo "  ✓ No-op diff validation (prevents identical code from polluting database)"
echo "  ✓ Larger context (128k tokens) and balanced sampling (5+5 programs)"
echo "  ✓ Clean database start (no old programs)"
echo ""

# Run evolution
python /root/openevolve/openevolve-run.py \
    src/algorithm.py \
    src/evaluator_v2.py \
    --config config/config_deepseek_r1_CLEAN.yaml \
    --iterations 20 \
    --output ./outputs/evolution/eyeriss_CLEAN_START \
    2>&1 | tee logs/optimized_test_$(date +%Y%m%d_%H%M%S).log

echo ""
echo "✅ Evolution test complete!"
echo "Log file saved to logs/optimized_test_*.log"
echo "Check for:"
echo "  - EDP values changing across iterations (not all identical)"
echo "  - No-op mutation errors (should see 'diff did not change code' if LLM still not modifying parameters)"
echo "  - Unique mapping directories in outputs/mappings/ (one per program)"
