#!/bin/bash
# Full Evolution Experiment (10 iterations)
# New Architecture V2: algorithm.py → evaluator_v2.py

LOG_DIR="logs"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${LOG_DIR}/evolution_10iter_${TIMESTAMP}.log"

echo "========================================" | tee -a "$LOG_FILE"
echo "Full Evolution Experiment (10 Iterations)" | tee -a "$LOG_FILE"
echo "New Architecture: algorithm.py → evaluator_v2.py" | tee -a "$LOG_FILE"
echo "Started at: $(date)" | tee -a "$LOG_FILE"
echo "Log file: $LOG_FILE" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

echo "========================================" | tee -a "$LOG_FILE"
echo "Soter Timeloop Mapping Evolution (V2)" | tee -a "$LOG_FILE"
echo "Architecture: algorithm.py → timeloop_interface.py → evaluator_v2.py" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# 1. Setup environment
echo "🔧 Setting up environment..." | tee -a "$LOG_FILE"
echo "  → Activating openevolve_env conda environment..." | tee -a "$LOG_FILE"
eval "$(conda shell.bash hook)"
conda activate openevolve_env

echo "  → Setting Timeloop paths..." | tee -a "$LOG_FILE"
export TIMELOOP_DIR="/root/timeloop"
export PATH="$TIMELOOP_DIR/build/bin:$PATH"

echo "  → Setting GLM API key..." | tee -a "$LOG_FILE"
export OPENAI_API_KEY="283fe07947104336948a068b2501e885.Jnb3Nou8WS0Fz7Yj"

echo "✅ Environment setup complete" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# 2. Verify environment
echo "🔍 Verifying environment..." | tee -a "$LOG_FILE"
echo "  → Python: $(python --version)" | tee -a "$LOG_FILE"
echo "  → OpenEvolve: $(python -c 'import openevolve; print("✅ Installed")' 2>/dev/null || echo '❌ Not found')" | tee -a "$LOG_FILE"
echo "  → Timeloop: $(which timeloop-mapper && echo '✅ Available' || echo '❌ Not found')" | tee -a "$LOG_FILE"
echo "  → GLM API Key: $([ -n "$OPENAI_API_KEY" ] && echo '✅ Set' || echo '❌ Not set')" | tee -a "$LOG_FILE"
echo "✅ Environment verification complete" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# 3. Configuration
echo "📋 Evolution Configuration (V2):" | tee -a "$LOG_FILE"
echo "  → Iterations: 10" | tee -a "$LOG_FILE"
echo "  → Log level: INFO" | tee -a "$LOG_FILE"
echo "  → Algorithm file: src/algorithm.py" | tee -a "$LOG_FILE"
echo "  → Evaluator: src/evaluator_v2.py" | tee -a "$LOG_FILE"
echo "  → Config: config/config_v2.yaml" | tee -a "$LOG_FILE"
echo "  → Database: outputs/evolution/eyeriss_mapping_v2_evolution" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# 4. Cleanup old temporary files
echo "🗑️  Cleaning old temporary files..." | tee -a "$LOG_FILE"
rm -f outputs/mappings/*.yaml 2>/dev/null
rm -f /tmp/*.stats.txt /tmp/*.map.txt 2>/dev/null
echo "✅ Cleanup complete" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# 5. Start evolution
echo "🚀 Starting OpenEvolve evolution (10 iterations)..." | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

cd /root/evolve_1108/cc_1108

# 临时修改config以运行10次迭代
cp config/config_v2.yaml config/config_v2_backup.yaml
sed -i 's/^max_iterations:.*/max_iterations: 10/' config/config_v2.yaml

# Run OpenEvolve
python -m openevolve \
    --program src/algorithm.py \
    --evaluator src/evaluator_v2.py \
    --config config/config_v2.yaml \
    2>&1 | tee -a "$LOG_FILE"

EVOLUTION_EXIT_CODE=${PIPESTATUS[0]}

# 恢复config
mv config/config_v2_backup.yaml config/config_v2.yaml

echo "" | tee -a "$LOG_FILE"
echo "Evolution complete!" | tee -a "$LOG_FILE"

if [ $EVOLUTION_EXIT_CODE -eq 0 ]; then
    echo "Best program metrics:" | tee -a "$LOG_FILE"
    python -c "
import json
try:
    with open('src/openevolve_output/best/best_program_info.json', 'r') as f:
        info = json.load(f)
        print('  metrics:', info.get('metrics', {}).get('metrics', {}))
        print('  artifacts:', info.get('metrics', {}).get('artifacts', {}))
except Exception as e:
    print('  Error reading best program:', e)
" | tee -a "$LOG_FILE"
fi

echo "" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
echo "✅ Evolution complete!" | tee -a "$LOG_FILE"
echo "📊 Results saved to: outputs/evolution/" | tee -a "$LOG_FILE"
echo "🗺️  Best mapping: outputs/mappings/generated_mapping.yaml" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

echo "========================================" | tee -a "$LOG_FILE"
echo "Test completed at: $(date)" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# 6. Results summary
echo "📊 Results Summary:" | tee -a "$LOG_FILE"
echo "  ✅ Evolution database created" | tee -a "$LOG_FILE"
ls -lh outputs/evolution/eyeriss_mapping_v2_evolution/ 2>/dev/null | tee -a "$LOG_FILE"
echo "  ✅ Mapping generated" | tee -a "$LOG_FILE"
ls -lh outputs/mappings/*.yaml 2>/dev/null | head -5 | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

echo "📈 Evolution Statistics:" | tee -a "$LOG_FILE"
python -c "
import json
import os
from pathlib import Path

db_path = Path('outputs/evolution/eyeriss_mapping_v2_evolution/programs')
if db_path.exists():
    programs = list(db_path.glob('*.json'))
    print(f'  → Total programs generated: {len(programs)}')

    # Count by status
    passed = 0
    failed = 0
    for prog in programs:
        with open(prog, 'r') as f:
            data = json.load(f)
            stage1 = data.get('metrics', {}).get('metrics', {}).get('stage1_passed', 0)
            if stage1 > 0:
                passed += 1
            else:
                failed += 1

    print(f'  → Constraint-satisfying programs: {passed}')
    print(f'  → Constraint-violating programs: {failed}')
    print(f'  → Success rate: {passed/len(programs)*100:.1f}%')
else:
    print('  → No programs found')
" | tee -a "$LOG_FILE"

echo "" | tee -a "$LOG_FILE"
echo "Full log saved to: $LOG_FILE" | tee -a "$LOG_FILE"
