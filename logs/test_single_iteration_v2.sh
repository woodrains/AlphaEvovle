#!/bin/bash
# Single Iteration Test for New Architecture (V2)

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="logs/evolution_v2_test_${TIMESTAMP}.log"

mkdir -p logs

echo "========================================" | tee -a $LOG_FILE
echo "Single Iteration Evolution Test (V2)" | tee -a $LOG_FILE
echo "New Architecture: algorithm.py → evaluator_v2.py" | tee -a $LOG_FILE
echo "Started at: $(date)" | tee -a $LOG_FILE
echo "Log file: $LOG_FILE" | tee -a $LOG_FILE
echo "========================================" | tee -a $LOG_FILE
echo "" | tee -a $LOG_FILE

bash scripts/run_evolution_v2.sh 1 DEBUG 2>&1 | tee -a $LOG_FILE

echo "" | tee -a $LOG_FILE
echo "========================================" | tee -a $LOG_FILE
echo "Test completed at: $(date)" | tee -a $LOG_FILE
echo "========================================" | tee -a $LOG_FILE
echo "" | tee -a $LOG_FILE

# 显示结果摘要
echo "📊 Results Summary:" | tee -a $LOG_FILE
if [ -d "src/openevolve_output" ]; then
    echo "  ✅ Evolution database created" | tee -a $LOG_FILE
    ls -lh src/openevolve_output | tee -a $LOG_FILE
else
    echo "  ❌ Evolution database not found" | tee -a $LOG_FILE
fi

if [ -f "outputs/mappings/generated_mapping.yaml" ]; then
    echo "  ✅ Mapping generated" | tee -a $LOG_FILE
else
    echo "  ❌ Mapping not generated" | tee -a $LOG_FILE
fi

echo "" | tee -a $LOG_FILE
