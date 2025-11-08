# OpenEvolve Soter Mapping Optimization

基于 OpenEvolve 框架的 Timeloop 映射优化实现，用于自动优化 DNN 算子到空间加速器（Eyeriss）的映射策略。

## 📁 项目结构

```
/root/evolve_1108/cc_1108/
├── config.yaml                 # OpenEvolve配置（核心）
├── initial_program.py          # 初始映射程序（含EVOLVE-BLOCK）
├── evaluator.py               # Timeloop评估器（分层评估）
├── constraint_checker.py      # 约束检查器（C_t/C_p验证）
├── prompts/
│   ├── system_message.txt     # 系统消息（映射优化专家）
│   └── fragments.json         # 提示片段（约束、优化策略）
├── in_config/                 # Timeloop配置
│   ├── eyeriss.yaml           # Eyeriss架构配置
│   ├── problem.yaml           # 问题定义（Conv层）
│   └── mapspace.yaml          # 映射空间约束
└── README.md                  # 本文档
```

## 🎯 核心功能

### 1. 映射策略演化
- **EVOLVE-BLOCK**：在 `initial_program.py` 中标记可演化的映射策略函数
- **LLM驱动优化**：GLM-4.6 自动生成改进的映射策略
- **约束感知**：所有修改自动满足 C_t（缓存容量）和 C_p（空间并行）约束

### 2. 分层评估
- **Stage 1**: 快速约束检查（< 5秒）
- **Stage 2**: Timeloop完整评估（性能指标）
- **Stage 3**: EDP分析与改进计算

### 3. Artifacts反馈
- 约束违反详情（供LLM学习）
- Timeloop性能统计
- 失败原因分析

## 🚀 快速开始

### 环境准备

```bash
# 1. 激活环境
conda activate rtl_pilot

# 2. 设置Timeloop路径
export PATH=/root/Soter_v4/Soter_v4/timeloop-v2.0/bin:$PATH
export LD_LIBRARY_PATH=/root/Soter_v4/Soter_v4/timeloop-v2.0/lib:$LD_LIBRARY_PATH

# 3. 设置GLM API Key
export GLM_API_KEY="283fe07947104336948a068b2501e885.Jnb3Nou8WS0Fz7Yj"

# 4. 验证Timeloop
timeloop-model --version
```

### 运行OpenEvolve

```bash
cd /root/openevolve

# 最小化测试（1迭代）
python openevolve-run.py \
  /root/evolve_1108/cc_1108/initial_program.py \
  /root/evolve_1108/cc_1108/evaluator.py \
  --config /root/evolve_1108/cc_1108/config.yaml \
  --iterations 1 \
  --log-level DEBUG

# 完整运行（50迭代）
python openevolve-run.py \
  /root/evolve_1108/cc_1108/initial_program.py \
  /root/evolve_1108/cc_1108/evaluator.py \
  --config /root/evolve_1108/cc_1108/config.yaml \
  --iterations 50
```

### 查看结果

```bash
# 查看演化轨迹
cd /root/evolve_1108/cc_1108/openevolve_output/eyeriss_mapping_evolution

# 最佳程序
ls checkpoints/best_program/

# 演化历史
cat logs/evolution_history.json
```

## 📊 配置说明

### config.yaml 关键参数

```yaml
# LLM配置
llm:
  primary_model: "glm-4.6"
  api_base: "https://open.bigmodel.cn/api/paas/v4/"
  temperature: 0.7           # 探索与利用平衡
  max_tokens: 8000           # 映射优化输出长度

# Database配置
database:
  population_size: 20        # 种群大小
  num_islands: 3             # 岛屿数量（多样性）
  feature_dimensions:
    - "latency"              # Timeloop延迟
    - "energy"               # Timeloop能耗
    - "mapping_diversity"    # 映射多样性

# Evaluator配置
evaluator:
  cascade_evaluation: true
  cascade_thresholds:
    - 0.0    # Stage1: 约束检查（必过）
    - 0.3    # Stage2: Timeloop评估（需达到baseline 30%）

# Soter特定配置
soter:
  architecture: "eyeriss"
  fitness_objectives:
    - "edp"       # Energy-Delay Product（主要目标）
    - "latency"   # 延迟
    - "energy"    # 能耗
```

## 🔧 核心组件详解

### initial_program.py

**EVOLVE-BLOCK 位置**：`line 123-189`

可演化的函数：
- `generate_mapping_strategy()` - 主策略生成
- `_get_dimension_order_baseline()` - 维度顺序（X_d）
- `_get_temporal_tiles_baseline()` - 时间分块（X_t）
- `_get_spatial_tiles_baseline()` - 空间并行（X_p）
- `_get_bypass_strategy_baseline()` - Bypass策略

### evaluator.py

**评估流程**：
1. 执行 `initial_program.py` 生成映射
2. **Stage 1**: 约束检查（C_t, C_p, budgets）
3. **Stage 2**: Timeloop评估（latency, energy, EDP）
4. **Stage 3**: 性能分析（改进百分比、分数计算）

**返回格式**：
```python
{
    "success": True,
    "final_score": 150.5,
    "metrics": {
        "edp": 1.2e9,
        "latency": 100000,
        "energy": 12000
    },
    "improvement": 15.3,  # 相对baseline改进百分比
    "artifacts": {
        "timeloop_stats": {...},
        "constraint_details": {...}
    }
}
```

### constraint_checker.py

**约束检查公式**：

**C_t（缓存容量）**：
```python
input_tile = N * P * Q * C
weight_tile = K * R * S * C
output_tile = P * Q * K * N
total_tile <= buffer_size[level]
```

**C_p（空间并行）**：
```python
spatial_product = Π(spatial_tiles) <= spmap_cstr[level]
```

**维度预算守恒**：
```python
Π(temporal_tiles[D]) × Π(spatial_tiles[D]) = original_D
```

## 🎓 优化策略指南

### Eyeriss架构特点
- **4层缓存层级**：DRAM → Global Buffer → Dummy → PE
- **168个PE**：支持 P/Q 维度的空间并行
- **Row Stationary数据流**：保持滤波器行在PE寄存器中

### 优化方向

**1. 最大化数据重用**
- 权重（K×R×S×C）尽量tile到Global Buffer（256KB）
- 输出激活值在PE层保持（16KB）

**2. 空间并行利用**
- Dummy层：P维度14倍并行
- Global层：P维度12倍并行
- R/S维度不并行（卷积核小）

**3. 维度顺序优化**
```python
# PE层（最小化数据搬运）
order = ["R", "S", "P", "Q", "C", "K", "N"]

# Global层（最大化权重重用）
order = ["C", "K", "P", "Q", "R", "S", "N"]

# DRAM层（批量并行）
order = ["N", "K", "C", "P", "Q", "R", "S"]
```

## 📈 预期改进

基于 AlphaEvolve 论文经验：
- **保守目标**：5-10% EDP reduction
- **期望目标**：10-20% EDP reduction
- **最佳目标**：20-30% EDP reduction

## 🐛 故障排查

### 1. Timeloop not found
```bash
which timeloop-model
export PATH=/root/Soter_v4/Soter_v4/timeloop-v2.0/bin:$PATH
```

### 2. GLM API调用失败
```bash
echo $GLM_API_KEY
curl -H "Authorization: Bearer $GLM_API_KEY" \
  https://open.bigmodel.cn/api/paas/v4/chat/completions
```

### 3. 约束检查失败率过高
- 调整 prompt 中的约束强调
- 增加 artifacts 详细度
- 降低 temperature（更保守探索）

### 4. Timeloop评估超时
- 增加 `evaluator.timeout`
- 检查映射生成是否合法
- 使用更小的problem规模测试

## 📚 参考文档

- [OpenEvolve适配方案](/root/evolve_1108/openevolve_soter_adaptation_plan.md)
- [Soter代码审查](/root/evolve_1108/docs/Soter_代码审查_1108.md)
- [Soter约束检查分析](/root/evolve_1108/docs/Soter_约束检查分析报告_1108.md)
- [GLM API文档](/root/evolve_1108/docs/GLM_api.md)
- [OpenEvolve官方文档](/root/openevolve/CLAUDE.md)

## 🔬 实验记录

### 监控指标
- `best_edp_per_generation` - 每代最佳EDP
- `constraint_violation_rate` - 约束违反率
- `llm_mutation_acceptance_rate` - LLM变异接受率
- `timeloop_evaluation_success_rate` - Timeloop评估成功率

### 日志位置
```bash
# OpenEvolve日志
/root/evolve_1108/cc_1108/openevolve_output/*/logs/evolution.log

# GLM调用日志（如果使用evolve_gpt封装）
/root/evolve_1108/evolve_gpt/runs/*/logs/glm_summary.jsonl
```

## 📝 许可证

本项目基于 OpenEvolve 框架，遵循其开源协议。
