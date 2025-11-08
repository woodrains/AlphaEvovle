#!/bin/bash
# ============================================
# Run Evolution with New Architecture (V2)
# 使用algorithm.py + evaluator_v2.py
# ============================================

set -e  # 遇到错误立即退出

# 读取参数
ITERATIONS=${1:-1}  # 默认1次迭代（测试用）
LOG_LEVEL=${2:-"INFO"}  # 默认INFO级别

echo "========================================"
echo "Soter Timeloop Mapping Evolution (V2)"
echo "Architecture: algorithm.py → timeloop_interface.py → evaluator_v2.py"
echo "========================================"
echo ""

# ============================================
# 设置环境
# ============================================
echo "🔧 Setting up environment..."
echo "  → Activating openevolve_env conda environment..."
source /root/miniconda3/etc/profile.d/conda.sh
conda activate openevolve_env

echo "  → Setting Timeloop paths..."
export PATH="/root/timeloop/build/bin:$PATH"
export LD_LIBRARY_PATH="/root/timeloop/build/lib:$LD_LIBRARY_PATH"

echo "  → Setting GLM API key..."
export OPENAI_API_KEY="283fe07947104336948a068b2501e885.Jnb3Nou8WS0Fz7Yj"

echo "✅ Environment setup complete"
echo ""

# ============================================
# 验证环境
# ============================================
echo "🔍 Verifying environment..."
echo "  → Python: $(python --version 2>&1)"
echo "  → OpenEvolve: $(python -c 'import openevolve; print("✅ Installed")' 2>&1 || echo "❌ Not found")"
echo "  → Timeloop: $(which timeloop-model &>/dev/null && echo "✅ Available" || echo "❌ Not found")"
echo "  → GLM API Key: $([ -n "$OPENAI_API_KEY" ] && echo "✅ Set" || echo "❌ Not set")"
echo "✅ Environment verification complete"
echo ""

# ============================================
# Evolution配置
# ============================================
echo "📋 Evolution Configuration (V2):"
echo "  → Iterations: $ITERATIONS"
echo "  → Log level: $LOG_LEVEL"
echo "  → Algorithm file: src/algorithm.py"
echo "  → Evaluator: src/evaluator_v2.py"
echo "  → Config: config/config_v2.yaml"
echo ""

# ============================================
# 清理旧的临时文件
# ============================================
echo "🗑️  Cleaning old temporary files..."
rm -rf outputs/timeloop_temp/* 2>/dev/null || true
rm -rf src/openevolve_output/temp/* 2>/dev/null || true
echo "✅ Cleanup complete"
echo ""

# ============================================
# 运行OpenEvolve
# ============================================
echo "🚀 Starting OpenEvolve evolution (New Architecture V2)..."
echo "========================================"
echo ""

python /root/openevolve/openevolve-run.py \
    /root/evolve_1108/cc_1108/src/algorithm.py \
    /root/evolve_1108/cc_1108/src/evaluator_v2.py \
    --config /root/evolve_1108/cc_1108/config/config_v2.yaml \
    --iterations $ITERATIONS \
    --log-level $LOG_LEVEL

echo ""
echo "========================================"
echo "✅ Evolution complete!"
echo "📊 Results saved to: outputs/evolution/"
echo "🗺️  Best mapping: outputs/mappings/generated_mapping.yaml"
echo "========================================"
