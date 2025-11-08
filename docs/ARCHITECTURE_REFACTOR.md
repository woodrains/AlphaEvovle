# Architecture Refactor: 分离算法演化和Timeloop接口

## 当前问题

**WARNING**: `No 'combined_score' metric found in evaluation results`

### 根本原因分析：

1. **LLM演化范围过大**：当前让LLM演化整个`initial_program.py`（390行），包含：
   - Timeloop YAML解析逻辑
   - 硬件约束计算
   - 映射格式转换
   - 文件I/O操作

2. **评估指标混乱**：
   - Stage1返回：`{"stage1_passed": 1.0}`
   - Stage2返回：`{"latency": ..., "energy": ..., "edp": ..., "stage2_passed": 1.0}`
   - OpenEvolve期望一个明确的`combined_score`作为fitness

3. **LLM焦点分散**：应该专注于**算法优化**（tile大小、dimension order、bypass策略），而非基础设施代码

## 新架构设计

### 核心思想：**让LLM只演化算法决策函数**

```
┌─────────────────────────────────────────────────────────────┐
│  LLM Evolution Scope (只演化这部分)                          │
│                                                              │
│  algorithm.py                                                │
│  ├── decide_temporal_tiles(level, problem_dims) -> Dict     │
│  ├── decide_spatial_tiles(level, problem_dims) -> Dict      │
│  ├── decide_dimension_order(level, problem_dims) -> List    │
│  └── decide_bypass_strategy(level, problem_dims) -> List    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  Fixed Infrastructure (不演化)                               │
│                                                              │
│  timeloop_interface.py                                       │
│  ├── load_config(arch, problem) -> Config                   │
│  ├── validate_algorithm(algo, config) -> Violations         │
│  ├── convert_to_mapping(algo_result, config) -> YAML        │
│  └── run_timeloop(mapping) -> Stats                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  Evaluator (evaluator.py)                                    │
│                                                              │
│  1. 加载algorithm.py                                         │
│  2. 调用algorithm的决策函数                                  │
│  3. 通过timeloop_interface转换+运行                          │
│  4. 计算fitness = f(EDP, latency, energy)                   │
│  5. 返回unified metrics: {"combined_score": fitness, ...}   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## 具体实现

### 1. algorithm.py (LLM演化的唯一文件，~100行)

```python
"""
Eyeriss Mapping Algorithm
LLM只演化这个文件中的EVOLVE-BLOCK

输入：problem_dims (N, K, C, P, Q, R, S)
输出：mapping_decisions (tiles, orders, bypass)
"""

# EVOLVE-BLOCK-START
def decide_temporal_tiles(level_idx: int, level_name: str,
                          problem_dims: Dict) -> Dict[str, int]:
    """
    决策时间分块（X_t参数）

    Args:
        level_idx: 层级索引 (0=PE, 4=Global, 5=DRAM)
        level_name: 层级名称 (PsumRegFile, GlobalBuffer, etc.)
        problem_dims: {N:1, K:64, C:64, P:56, Q:56, R:3, S:3}

    Returns:
        temporal_tiles: {N:1, K:4, C:1, P:7, Q:8, R:1, S:1}
    """
    # BASELINE: 保守的均匀分块
    if level_name == "GlobalBuffer":
        return {'N': 1, 'K': 4, 'C': 1, 'P': 7, 'Q': 8, 'R': 1, 'S': 1}
    elif level_name == "DRAM":
        return {'N': 1, 'K': 16, 'C': 64, 'P': 8, 'Q': 7, 'R': 3, 'S': 3}
    else:
        return {dim: 1 for dim in problem_dims}

def decide_spatial_tiles(level_idx: int, level_name: str,
                        problem_dims: Dict) -> Dict[str, int]:
    """决策空间并行（X_p参数）"""
    # BASELINE: 无空间并行
    return {dim: 1 for dim in problem_dims}

def decide_dimension_order(level_idx: int, level_name: str) -> List[str]:
    """决策维度遍历顺序（X_d参数）"""
    # BASELINE: 固定顺序
    baseline_orders = {
        0: ["R", "S", "P", "Q", "C", "K", "N"],  # PE
        4: ["C", "K", "P", "Q", "R", "S", "N"],  # Global
        5: ["N", "K", "C", "P", "Q", "R", "S"]   # DRAM
    }
    return baseline_orders.get(level_idx, ["N", "K", "C", "P", "Q", "R", "S"])

def decide_bypass_strategy(level_idx: int, level_name: str) -> List[str]:
    """决策Bypass策略"""
    # BASELINE: 不bypass
    return []
# EVOLVE-BLOCK-END

# ============================================
# 主接口（被evaluator调用）
# ============================================
def generate_mapping_decisions(problem_dims: Dict,
                                buffer_levels: List[str]) -> Dict:
    """
    生成完整的映射决策

    Args:
        problem_dims: 问题维度 {N, K, C, P, Q, R, S}
        buffer_levels: buffer层级列表

    Returns:
        mapping_decisions: {
            "levels": [
                {
                    "level_name": "GlobalBuffer",
                    "level_index": 4,
                    "temporal_tiles": {...},
                    "spatial_tiles": {...},
                    "dimension_order": [...],
                    "bypass": [...]
                },
                ...
            ]
        }
    """
    decisions = {"levels": []}

    for level_idx, level_name in enumerate(buffer_levels):
        level_decision = {
            "level_name": level_name,
            "level_index": level_idx,
            "temporal_tiles": decide_temporal_tiles(level_idx, level_name, problem_dims),
            "spatial_tiles": decide_spatial_tiles(level_idx, level_name, problem_dims),
            "dimension_order": decide_dimension_order(level_idx, level_name),
            "bypass": decide_bypass_strategy(level_idx, level_name)
        }
        decisions["levels"].append(level_decision)

    return decisions
```

### 2. timeloop_interface.py (固定，不演化)

```python
"""
Timeloop接口层
负责：配置加载、约束检查、格式转换、Timeloop执行
"""

class TimeloopInterface:
    def __init__(self, config_dir: str):
        self.config_dir = Path(config_dir)
        self.arch_config = self._load_yaml("eyeriss.yaml")
        self.problem_config = self._load_yaml("problem.yaml")

        # 解析硬件参数
        self.buffer_levels = self._parse_buffer_hierarchy()
        self.buffer_sizes = self._parse_buffer_sizes()
        self.spatial_constraints = self._parse_spatial_constraints()
        self.problem_dims = self._parse_problem_dimensions()

    def validate_decisions(self, decisions: Dict) -> Tuple[bool, List[Dict]]:
        """
        验证算法决策是否满足约束

        Returns:
            (is_valid, violations)
        """
        violations = []
        violations.extend(self._check_buffer_capacity(decisions))
        violations.extend(self._check_spatial_constraints(decisions))
        violations.extend(self._check_dimension_budgets(decisions))
        return (len(violations) == 0, violations)

    def convert_to_mapping(self, decisions: Dict) -> str:
        """
        将算法决策转换为Timeloop mapping YAML

        Returns:
            mapping_file_path
        """
        mapping = {"mapping": []}

        for level in decisions["levels"]:
            # 添加temporal mapping
            mapping["mapping"].append({
                "target": level["level_name"],
                "type": "temporal",
                "factors": self._format_factors(level["temporal_tiles"]),
                "permutation": "".join(level["dimension_order"])
            })

            # 添加datatype mapping
            mapping["mapping"].append(
                self._create_datatype_mapping(level)
            )

            # 添加spatial mapping (if有)
            if any(v > 1 for v in level["spatial_tiles"].values()):
                mapping["mapping"].append({
                    "target": level["level_name"],
                    "type": "spatial",
                    "factors": self._format_factors(level["spatial_tiles"]),
                    "permutation": "".join(level["dimension_order"])
                })

        # 保存YAML
        output_file = self.config_dir.parent / "outputs" / "mappings" / "generated.yaml"
        with open(output_file, 'w') as f:
            yaml.dump(mapping, f)

        return str(output_file)

    def run_timeloop(self, mapping_file: str) -> Dict:
        """
        运行Timeloop仿真

        Returns:
            stats: {"latency": ..., "energy": ..., "edp": ...}
        """
        # ... (现有的_run_timeloop_stage2逻辑)
```

### 3. evaluator.py (重构，返回unified metrics)

```python
"""
评估器 - 连接algorithm和timeloop_interface
"""

def evaluate(algorithm_path: str) -> Dict[str, Any]:
    """
    OpenEvolve调用的统一评估函数

    Returns:
        {
            "metrics": {
                "combined_score": float,  # ← 主fitness (越大越好)
                "edp": float,             # ← 用于分析
                "latency": float,         # ← feature dimension
                "energy": float           # ← feature dimension
            },
            "artifacts": {...}
        }
    """
    interface = TimeloopInterface("/root/evolve_1108/cc_1108/config/timeloop")

    # Step 1: 动态导入算法
    spec = importlib.util.spec_from_file_location("algorithm", algorithm_path)
    algo_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(algo_module)

    # Step 2: 调用算法生成决策
    decisions = algo_module.generate_mapping_decisions(
        problem_dims=interface.problem_dims,
        buffer_levels=interface.buffer_levels
    )

    # Step 3: 约束检查
    is_valid, violations = interface.validate_decisions(decisions)
    if not is_valid:
        return {
            "metrics": {
                "combined_score": -1000.0,  # 失败惩罚
                "edp": 0.0,
                "latency": 0.0,
                "energy": 0.0
            },
            "artifacts": {
                "stage": "constraint_check_failed",
                "violations": violations
            }
        }

    # Step 4: 转换为Timeloop格式
    mapping_file = interface.convert_to_mapping(decisions)

    # Step 5: 运行Timeloop
    stats = interface.run_timeloop(mapping_file)

    # Step 6: 计算combined_score
    # 目标: 最小化EDP，所以fitness = -EDP (或 1/EDP归一化)
    edp = stats["edp"]
    baseline_edp = 1e12  # 从baseline测量获取

    # Fitness设计: 负EDP（越小的EDP -> 越大的score）
    # 归一化到0-100范围
    combined_score = max(0, (1 - edp / baseline_edp) * 100)

    return {
        "metrics": {
            "combined_score": combined_score,  # ← OpenEvolve的主fitness
            "edp": edp,
            "latency": stats["latency"],
            "energy": stats["energy"]
        },
        "artifacts": {
            "stage": "evaluation_complete",
            "timeloop_stats": stats,
            "mapping_decisions": decisions
        }
    }
```

## 关键改进

### 1. **LLM专注度提升**
- 演化文件从390行 → ~100行
- 只包含纯算法逻辑，无基础设施代码
- LLM可以更聚焦于优化策略

### 2. **评估指标统一**
- 单一评估函数`evaluate()`
- 返回明确的`combined_score`
- 消除warning，OpenEvolve正确优化

### 3. **可维护性提升**
- 算法(`algorithm.py`) vs 基础设施(`timeloop_interface.py`)清晰分离
- 修改Timeloop接口不影响演化
- 易于测试和调试

### 4. **更好的Fitness设计**
```python
# 选项1: 负EDP（简单直接）
combined_score = -edp

# 选项2: 归一化百分比
combined_score = (1 - edp/baseline_edp) * 100

# 选项3: 多目标加权
combined_score = w1*(1-edp/baseline) + w2*(1-latency/baseline) + w3*(1-energy/baseline)
```

## 迁移步骤

1. ✅ 创建`src/algorithm.py` - 提取决策函数
2. ✅ 创建`src/timeloop_interface.py` - 封装Timeloop交互
3. ✅ 重构`src/evaluator.py` - 统一评估接口
4. ✅ 更新`config/config.yaml` - 指向新的algorithm.py
5. ✅ 测试端到端流程
6. ✅ 运行单次演化验证

## 预期效果

- ✅ 消除"No 'combined_score'"警告
- ✅ LLM生成的代码更简洁、更聚焦
- ✅ 演化速度提升（代码更短，LLM推理更快）
- ✅ 更容易实现高级优化策略
