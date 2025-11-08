#!/bin/bash
# 单次迭代演化测试 - 带详细日志

# 设置日志文件
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="logs/evolution_test_${TIMESTAMP}.log"

echo "========================================" | tee -a $LOG_FILE
echo "Single Iteration Evolution Test" | tee -a $LOG_FILE
echo "Started at: $(date)" | tee -a $LOG_FILE
echo "Log file: $LOG_FILE" | tee -a $LOG_FILE
echo "========================================" | tee -a $LOG_FILE

# 运行演化并记录所有输出
bash scripts/run_evolution.sh 1 DEBUG 2>&1 | tee -a $LOG_FILE

# 记录完成状态
echo "" | tee -a $LOG_FILE
echo "========================================" | tee -a $LOG_FILE
echo "Test completed at: $(date)" | tee -a $LOG_FILE
echo "========================================" | tee -a $LOG_FILE

# 显示结果摘要
echo "" | tee -a $LOG_FILE
echo "📊 Results Summary:" | tee -a $LOG_FILE
if [ -d "outputs/evolution/eyeriss_mapping_evolution" ]; then
    echo "  ✅ Evolution database created" | tee -a $LOG_FILE
    ls -lh outputs/evolution/eyeriss_mapping_evolution/ | tee -a $LOG_FILE
else
    echo "  ❌ Evolution database not found" | tee -a $LOG_FILE
fi

if [ -f "outputs/mappings/generated_mapping.yaml" ]; then
    echo "  ✅ Mapping generated" | tee -a $LOG_FILE
else
    echo "  ❌ Mapping not found" | tee -a $LOG_FILE
fi

echo "" | tee -a $LOG_FILE
echo "Full log saved to: $LOG_FILE"
