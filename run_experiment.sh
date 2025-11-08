#!/bin/bash

# OpenEvolve Soter 映射优化 - 快速启动脚本
# 使用方法: bash run_experiment.sh [test|full]

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查命令是否存在
check_command() {
    if ! command -v $1 &> /dev/null; then
        print_error "$1 not found!"
        return 1
    else
        print_success "$1 found: $(which $1)"
        return 0
    fi
}

# 步骤1: 环境检查
print_info "========== Step 1: Environment Check =========="

# 检查conda环境
if [ -z "$CONDA_DEFAULT_ENV" ]; then
    print_warning "Conda environment not activated!"
    print_info "Activating rtl_pilot environment..."
    source /root/miniconda3/bin/activate rtl_pilot
else
    print_success "Conda environment: $CONDA_DEFAULT_ENV"
fi

# 检查Python
check_command python || exit 1
python --version

# 检查Timeloop
print_info "Setting up Timeloop environment..."
export PATH=/root/Soter_v4/Soter_v4/timeloop-v2.0/bin:$PATH
export LD_LIBRARY_PATH=/root/Soter_v4/Soter_v4/timeloop-v2.0/lib:$LD_LIBRARY_PATH

check_command timeloop-model || {
    print_error "Timeloop not found! Please install Timeloop first."
    exit 1
}

timeloop-model --version

# 检查GLM API Key
print_info "Checking GLM API Key..."
export GLM_API_KEY="283fe07947104336948a068b2501e885.Jnb3Nou8WS0Fz7Yj"
if [ -z "$GLM_API_KEY" ]; then
    print_error "GLM_API_KEY not set!"
    exit 1
else
    print_success "GLM_API_KEY configured"
fi

# 步骤2: 路径设置
print_info "========== Step 2: Path Setup =========="

PROJECT_DIR="/root/evolve_1108/cc_1108"
OPENEVOLVE_DIR="/root/openevolve"

if [ ! -d "$PROJECT_DIR" ]; then
    print_error "Project directory not found: $PROJECT_DIR"
    exit 1
fi

if [ ! -d "$OPENEVOLVE_DIR" ]; then
    print_error "OpenEvolve directory not found: $OPENEVOLVE_DIR"
    exit 1
fi

print_success "Project directory: $PROJECT_DIR"
print_success "OpenEvolve directory: $OPENEVOLVE_DIR"

# 步骤3: 文件验证
print_info "========== Step 3: File Verification =========="

REQUIRED_FILES=(
    "$PROJECT_DIR/config.yaml"
    "$PROJECT_DIR/initial_program.py"
    "$PROJECT_DIR/evaluator.py"
    "$PROJECT_DIR/constraint_checker.py"
    "$PROJECT_DIR/in_config/eyeriss.yaml"
    "$PROJECT_DIR/in_config/problem.yaml"
    "$PROJECT_DIR/in_config/mapspace.yaml"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ -f "$file" ]; then
        print_success "Found: $(basename $file)"
    else
        print_error "Missing: $file"
        exit 1
    fi
done

# 步骤4: 确定运行模式
print_info "========== Step 4: Run Mode Selection =========="

MODE=${1:-test}

if [ "$MODE" == "test" ]; then
    ITERATIONS=1
    LOG_LEVEL="DEBUG"
    print_info "Running in TEST mode (1 iteration, DEBUG logging)"
elif [ "$MODE" == "full" ]; then
    ITERATIONS=50
    LOG_LEVEL="INFO"
    print_info "Running in FULL mode (50 iterations, INFO logging)"
else
    print_error "Invalid mode: $MODE. Use 'test' or 'full'"
    exit 1
fi

# 步骤5: 运行OpenEvolve
print_info "========== Step 5: Running OpenEvolve =========="

cd "$OPENEVOLVE_DIR"

print_info "Command:"
echo "python openevolve-run.py \\"
echo "  $PROJECT_DIR/initial_program.py \\"
echo "  $PROJECT_DIR/evaluator.py \\"
echo "  --config $PROJECT_DIR/config.yaml \\"
echo "  --iterations $ITERATIONS \\"
echo "  --log-level $LOG_LEVEL"

echo ""
print_warning "Press Ctrl+C to cancel, or wait 5 seconds to start..."
sleep 5

python openevolve-run.py \
  "$PROJECT_DIR/initial_program.py" \
  "$PROJECT_DIR/evaluator.py" \
  --config "$PROJECT_DIR/config.yaml" \
  --iterations $ITERATIONS \
  --log-level $LOG_LEVEL

# 步骤6: 结果总结
print_info "========== Step 6: Results Summary =========="

OUTPUT_DIR="$PROJECT_DIR/openevolve_output/eyeriss_mapping_evolution"

if [ -d "$OUTPUT_DIR" ]; then
    print_success "Output directory: $OUTPUT_DIR"

    if [ -d "$OUTPUT_DIR/checkpoints/best_program" ]; then
        print_success "Best program found!"
        ls -lh "$OUTPUT_DIR/checkpoints/best_program/"
    else
        print_warning "No best program yet (may appear after more iterations)"
    fi

    if [ -f "$OUTPUT_DIR/logs/evolution.log" ]; then
        print_success "Evolution log created"
        print_info "Last 10 lines:"
        tail -10 "$OUTPUT_DIR/logs/evolution.log"
    fi
else
    print_warning "Output directory not created yet"
fi

print_success "========== Experiment Complete! =========="
print_info "To view results:"
echo "  cd $OUTPUT_DIR"
echo "  ls checkpoints/"
echo "  cat logs/evolution.log"
