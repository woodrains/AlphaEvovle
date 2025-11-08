# OpenEvolve 适配 Soter 映射优化完整方案

**目标场景**: 将张量计算（GEMM、Conv2D等）高效映射到空间加速器（Eyeriss、Simba、TensorCore）

**参考成功案例**: `/root/openevolve/examples/mlx_metal_kernel_opt/`

**适配日期**: 2025-11-08

---

## 一、总体架构设计

### 1.1 核心思路对比

| 维度 | MLX Metal案例 | Soter映射场景 |
|------|---------------|---------------|
| **优化目标** | Metal GPU kernel代码 | Timeloop映射参数（X_t, X_p, X_d） |
| **评估方式** | 编译+基准测试（MLX） | Timeloop模拟器评估 |
| **演化对象** | Metal kernel源码（EVOLVE-BLOCK） | 映射决策序列（sol向量） |
| **约束检查** | GPU编译错误 + 正确性测试 | C_t缓存容量 + C_p并行约束 |
| **LLM模型** | Gemini 2.5 Flash + Pro | GLM-4.6 |
| **反馈机制** | Artifacts（性能指标、错误信息） | Artifacts（Timeloop stats、约束违反） |

### 1.2 适配方案关键创新点

1. **结构化映射表示**: 将Soter的sol向量转换为可演化的JSON/YAML格式
2. **约束先行评估**: 在Timeloop前用ConstraintChecker快速验证C_t/C_p
3. **分层评估策略**: Stage1快速约束检查 → Stage2 Timeloop评估
4. **增强Artifacts**: 注入约束违反详情、Timeloop性能统计
5. **GLM-4.6专属提示**: 针对映射优化的结构化prompt设计

---

## 二、目录结构设计

```
/root/openevolve/examples/soter_mapping_opt/
├── config.yaml                 # OpenEvolve配置（核心）
├── initial_program.py          # 初始映射程序（含EVOLVE-BLOCK）
├── evaluator.py               # Timeloop评估器（分层评估）
├── constraint_checker.py      # 约束检查器（C_t/C_p验证）
├── mapping_parser.py          # 映射解析器（sol ↔ 结构化表示）
├── prompts/
│   ├── system_message.txt     # 系统消息（映射优化专家）
│   └── fragments.json         # 提示片段（约束、优化策略）
├── in_config/                 # Timeloop配置（从Soter复制）
│   ├── eyeriss.yaml
│   ├── problem.yaml
│   └── mapspace.yaml
└── README.md                  # 说明文档
```

---

## 三、核心文件设计

### 3.1 `config.yaml` - OpenEvolve配置

基于mlx_metal_kernel_opt的config.yaml，针对性修改：

```yaml
# ============================================
# OpenEvolve Configuration for Soter Mapping Optimization
# Target: Optimize tensor-to-accelerator mappings via Timeloop
# ============================================

max_iterations: 50              # 演化迭代次数
checkpoint_interval: 10         # 检查点保存间隔
log_level: "INFO"

# ==================== LLM配置 ====================
llm:
  # GLM-4.6 作为主力模型
  primary_model: "glm-4.6"
  primary_model_weight: 1.0

  # API配置（基于 /root/evolve_1108/docs/GLM_api.md）
  api_base: "https://open.bigmodel.cn/api/paas/v4/"
  api_key: "283fe07947104336948a068b2501e885.Jnb3Nou8WS0Fz7Yj"  # 从GLM_api.md

  # 生成参数
  temperature: 0.7         # 平衡探索与利用（MLX用0.6，映射问题稍高）
  top_p: 0.95
  max_tokens: 8000         # 映射优化不需要太长输出
  timeout: 600             # 10分钟（Timeloop评估可能慢）

# ==================== Prompt配置 ====================
prompt:
  # 自定义系统消息（见下文详细设计）
  system_message: "mapping_expert_system"

  # 提示模板目录
  template_dir: "./prompts"

  # Top程序数量（用于学习）
  num_top_programs: 3
  num_diverse_programs: 2

  # Artifacts配置
  include_artifacts: true
  max_artifact_bytes: 4096      # 限制Timeloop输出大小
  artifact_security_filter: true

  # 映射优化特定配置
  include_constraint_violations: true   # 新增：包含约束违反详情
  include_timeloop_stats: true          # 新增：包含Timeloop统计

# ==================== Database配置 ====================
database:
  db_path: "./openevolve_output/eyeriss_mapping_evolution"
  population_size: 20          # 映射空间大，需要更多种群
  archive_size: 10
  num_islands: 3               # 岛屿模型维持多样性

  # 特征维度（MAP-Elites）
  feature_dimensions:
    - "latency"      # Timeloop返回的latency（已归一化）
    - "energy"       # Timeloop返回的energy（已归一化）
    - "mapping_diversity"  # 自定义：映射结构多样性

  # 采样策略
  elite_selection_ratio: 0.4
  exploitation_ratio: 0.6      # 更关注利用（映射空间复杂）
  exploration_ratio: 0.4

# ==================== Evaluator配置 ====================
evaluator:
  timeout: 600                 # 单次Timeloop评估超时
  parallel_evaluations: 4      # 并行评估数量

  # 分层评估配置（借鉴mlx_metal_kernel_opt的bulletproof策略）
  cascade_evaluation: true
  cascade_thresholds:
    - 0.0    # Stage1: 约束检查（通过即可）
    - 0.3    # Stage2: Timeloop评估（需达到baseline 30%）

  # Timeloop配置
  timeloop_bin: "timeloop-model"  # 确保在PATH中
  architecture: "eyeriss"          # 目标加速器
  in_config_dir: "./in_config"

  # 约束检查配置
  use_constraint_checker: true
  constraint_checker_timeout: 5    # 快速约束检查

# ==================== Evolution配置 ====================
diff_based_evolution: false       # 映射优化用JSON Patch而非代码diff
allow_full_rewrites: true         # 允许完全重写映射
max_code_length: 50000            # 映射程序不会太长

# ==================== Soter特定配置 ====================
soter:
  architecture: "eyeriss"
  problem_file: "conv_layer_resnet50_layer1.yaml"

  # 映射参数范围（从Soter约束分析报告）
  max_buffer_levels: 4           # DRAM/Global/Dummy/PE
  dimension_order: ["N", "K", "C", "P", "Q", "R", "S"]
  num_primes: 5                  # 质因数分解维度

  # 优化目标
  fitness_objectives:
    - "edp"       # Energy-Delay Product（主要）
    - "latency"   # 延迟（次要）
    - "energy"    # 能耗（次要）
```

---

### 3.2 `initial_program.py` - 初始映射程序

将Soter的actor.py逻辑封装为可演化的程序：

```python
"""
初始映射程序 - Eyeriss加速器
基于Soter的baseline策略，提供EVOLVE-BLOCK供OpenEvolve优化

这个程序的结构：
1. 读取Timeloop配置（架构、问题）
2. 生成映射决策（EVOLVE-BLOCK中的启发式策略）
3. 输出Timeloop可接受的mapping YAML
"""

import os
import yaml
import json
import numpy as np
from typing import Dict, List, Tuple, Any


class SoterMappingGenerator:
    """Soter映射生成器 - 封装Timeloop映射逻辑"""

    def __init__(self, arch_file: str, problem_file: str, mapspace_file: str):
        """
        初始化映射生成器

        Args:
            arch_file: 架构配置文件路径（eyeriss.yaml）
            problem_file: 问题配置文件路径（conv层定义）
            mapspace_file: 映射空间约束文件路径
        """
        self.arch_config = self._load_yaml(arch_file)
        self.problem_config = self._load_yaml(problem_file)
        self.mapspace_config = self._load_yaml(mapspace_file)

        # 解析架构信息（来自Soter的timeloop_env.py）
        self.buffer_levels = self._parse_buffer_hierarchy()
        self.buffer_sizes = self._parse_buffer_sizes()
        self.buffer_spmap_cstr = self._parse_spatial_constraints()

        # 解析问题维度（N, K, C, P, Q, R, S）
        self.dimensions = self._parse_problem_dimensions()
        self.dimension_primes = self._factorize_dimensions()

    def _load_yaml(self, filepath: str) -> Dict:
        """加载YAML配置文件"""
        with open(filepath, 'r') as f:
            return yaml.safe_load(f)

    def _parse_buffer_hierarchy(self) -> List[str]:
        """解析缓存层级（从Soter的get_buffer_info）"""
        # 简化版：假设Eyeriss标准4层
        return ["DRAM", "GlobalBuffer", "Dummy", "PE"]

    def _parse_buffer_sizes(self) -> Dict[str, int]:
        """解析各层缓存容量（C_t约束）"""
        # 从arch_config中提取，返回 {level_name: size_bytes}
        # 简化示例
        return {
            "l0": 16 * 1024,      # PE level: 16KB
            "l1": 1024,           # Dummy: 1KB
            "l2": 256 * 1024,     # Global: 256KB
            "l3": 1024 * 1024 * 1024  # DRAM: 1GB
        }

    def _parse_spatial_constraints(self) -> Dict[str, int]:
        """解析空间并行约束（C_p约束）"""
        # 从arch_config中提取PE数量比例
        return {
            "l0": 1,    # PE level无空间并行
            "l1": 14,   # Dummy层14x并行
            "l2": 12,   # Global层12x并行
            "l3": 1     # DRAM无并行
        }

    def _parse_problem_dimensions(self) -> Dict[str, int]:
        """解析问题维度（N, K, C, P, Q, R, S）"""
        prob = self.problem_config.get('problem', {}).get('instance', {})
        return {
            'N': prob.get('N', 1),
            'K': prob.get('K', 64),
            'C': prob.get('C', 64),
            'P': prob.get('P', 56),
            'Q': prob.get('Q', 56),
            'R': prob.get('R', 3),
            'S': prob.get('S', 3)
        }

    def _factorize_dimensions(self) -> Dict[str, List[int]]:
        """质因数分解各维度（用于tile决策）"""
        def prime_factors(n):
            factors = []
            d = 2
            while d * d <= n:
                while n % d == 0:
                    factors.append(d)
                    n //= d
                d += 1
            if n > 1:
                factors.append(n)
            return factors

        return {dim: prime_factors(size)
                for dim, size in self.dimensions.items()}


# ============================================
# EVOLVE-BLOCK-START: 可演化的映射策略
# ============================================

    def generate_mapping_strategy(self) -> Dict[str, Any]:
        """
        生成映射策略（BASELINE版本 - 供OpenEvolve优化）

        这个函数是演化的核心：
        - 输入：问题维度、架构约束
        - 输出：结构化的映射决策（tile、order、parallel）

        OpenEvolve将通过LLM重写这个策略以优化性能。

        Returns:
            mapping_strategy: 包含各层的tile/order/parallel决策
        """

        # ===== BASELINE策略：保守的均匀分块 =====

        strategy = {
            "meta": {
                "version": "baseline_v1",
                "description": "Conservative uniform tiling for Eyeriss",
                "target_architecture": "eyeriss",
                "problem_dimensions": self.dimensions
            },
            "levels": []
        }

        # 为每个缓存层级生成映射决策
        for level_idx, level_name in enumerate(self.buffer_levels):
            level_strategy = {
                "level_name": level_name,
                "level_index": level_idx,
                "dimension_order": self._get_dimension_order_baseline(level_idx),
                "temporal_tiles": self._get_temporal_tiles_baseline(level_idx),
                "spatial_tiles": self._get_spatial_tiles_baseline(level_idx),
                "bypass": self._get_bypass_strategy_baseline(level_idx)
            }
            strategy["levels"].append(level_strategy)

        return strategy

    def _get_dimension_order_baseline(self, level_idx: int) -> List[str]:
        """
        BASELINE: 维度遍历顺序（X_d参数）

        优化方向（供LLM参考）：
        - 改变顺序可影响数据重用模式
        - 不同层级应有不同的最优顺序
        - Eyeriss论文建议：R/S在内层，N/K在外层
        """
        # Baseline: 固定顺序（Soter的default）
        baseline_orders = {
            0: ["R", "S", "P", "Q", "C", "K", "N"],  # PE层
            1: ["P", "Q", "R", "S", "C", "K", "N"],  # Dummy层
            2: ["C", "K", "P", "Q", "R", "S", "N"],  # Global层
            3: ["N", "K", "C", "P", "Q", "R", "S"]   # DRAM层
        }
        return baseline_orders.get(level_idx, ["N", "K", "C", "P", "Q", "R", "S"])

    def _get_temporal_tiles_baseline(self, level_idx: int) -> Dict[str, int]:
        """
        BASELINE: 时间分块大小（X_t参数）

        优化方向（供LLM参考）：
        - 需满足C_t约束（buffer容量）
        - 较大tile提高数据重用，但可能超容量
        - 应利用维度的质因数结构
        """
        # Baseline: 保守的小tile（确保满足C_t）
        baseline_tiles = {
            0: {"R": 1, "S": 1, "P": 1, "Q": 1, "C": 1, "K": 1, "N": 1},  # PE: 最小
            1: {"P": 2, "Q": 2, "R": 1, "S": 1, "C": 1, "K": 1, "N": 1},  # Dummy
            2: {"C": 4, "K": 4, "P": 7, "Q": 7, "R": 1, "S": 1, "N": 1},  # Global
            3: {"N": 1, "K": 16, "C": 16, "P": 14, "Q": 14, "R": 3, "S": 3}  # DRAM
        }
        return baseline_tiles.get(level_idx, {dim: 1 for dim in self.dimensions})

    def _get_spatial_tiles_baseline(self, level_idx: int) -> Dict[str, int]:
        """
        BASELINE: 空间并行分块（X_p参数）

        优化方向（供LLM参考）：
        - 需满足C_p约束（空间并行容量）
        - 空间并行可减少延迟，但受硬件限制
        - Eyeriss支持P/Q维度的空间展开
        """
        # Baseline: 保守的空间并行（确保满足C_p）
        baseline_spatial = {
            0: {"N": 1, "K": 1, "C": 1, "P": 1, "Q": 1, "R": 1, "S": 1},  # PE无并行
            1: {"N": 1, "K": 1, "C": 1, "P": 14, "Q": 1, "R": 1, "S": 1}, # Dummy: P=14
            2: {"N": 1, "K": 1, "C": 1, "P": 12, "Q": 1, "R": 1, "S": 1}, # Global: P=12
            3: {"N": 1, "K": 1, "C": 1, "P": 1, "Q": 1, "R": 1, "S": 1}   # DRAM无并行
        }
        return baseline_spatial.get(level_idx, {dim: 1 for dim in self.dimensions})

    def _get_bypass_strategy_baseline(self, level_idx: int) -> List[str]:
        """
        BASELINE: Bypass策略（哪些数据跳过此层）

        优化方向（供LLM参考）：
        - Bypass可减少无效数据搬运
        - 需权衡数据重用与带宽压力
        """
        # Baseline: 不bypass（最保守）
        return []

# EVOLVE-BLOCK-END
# ============================================

    def convert_to_timeloop_mapping(self, strategy: Dict[str, Any]) -> Dict:
        """
        将结构化策略转换为Timeloop mapping YAML格式

        Args:
            strategy: generate_mapping_strategy()的输出

        Returns:
            timeloop_mapping: Timeloop可接受的mapping配置
        """
        mapping = {
            "mapping": []
        }

        for level_strategy in strategy["levels"]:
            level_mapping = {
                "target": level_strategy["level_name"],
                "type": "temporal",
                "factors": " ".join([
                    f"{dim}={size}"
                    for dim, size in level_strategy["temporal_tiles"].items()
                ]),
                "permutation": " ".join(level_strategy["dimension_order"])
            }
            mapping["mapping"].append(level_mapping)

            # 添加空间并行（如果有）
            spatial_tiles = level_strategy["spatial_tiles"]
            if any(v > 1 for v in spatial_tiles.values()):
                spatial_mapping = {
                    "target": level_strategy["level_name"],
                    "type": "spatial",
                    "factors": " ".join([
                        f"{dim}={size}"
                        for dim, size in spatial_tiles.items() if size > 1
                    ])
                }
                mapping["mapping"].append(spatial_mapping)

        return mapping

    def save_mapping_to_file(self, mapping: Dict, output_path: str):
        """保存映射到YAML文件"""
        with open(output_path, 'w') as f:
            yaml.dump(mapping, f, default_flow_style=False)


# ============================================
# 主执行逻辑
# ============================================

def main():
    """主函数 - 被OpenEvolve evaluator调用"""

    # 配置文件路径
    in_config_dir = os.path.join(os.path.dirname(__file__), "in_config")
    arch_file = os.path.join(in_config_dir, "eyeriss.yaml")
    problem_file = os.path.join(in_config_dir, "problem.yaml")
    mapspace_file = os.path.join(in_config_dir, "mapspace.yaml")

    # 创建映射生成器
    generator = SoterMappingGenerator(arch_file, problem_file, mapspace_file)

    # 生成映射策略（EVOLVE-BLOCK会被OpenEvolve优化）
    strategy = generator.generate_mapping_strategy()

    # 转换为Timeloop格式
    timeloop_mapping = generator.convert_to_timeloop_mapping(strategy)

    # 保存结果
    output_path = os.path.join(in_config_dir, "generated_mapping.yaml")
    generator.save_mapping_to_file(timeloop_mapping, output_path)

    print(f"✅ Mapping generated successfully: {output_path}")
    print(f"📊 Strategy version: {strategy['meta']['version']}")

    return strategy


if __name__ == "__main__":
    result = main()
```

---

### 3.3 `evaluator.py` - Timeloop评估器

借鉴mlx_metal_kernel_opt的bulletproof策略，实现分层评估：

```python
"""
Timeloop映射评估器 - 分层评估 + 约束检查
借鉴mlx_metal_kernel_opt的bulletproof策略，确保稳健性

评估流程：
Stage 1: 快速约束检查（C_t/C_p验证）
Stage 2: Timeloop完整评估（性能指标）
Stage 3: 增强分析（EDP、能耗分解）
"""

import os
import sys
import json
import subprocess
import tempfile
import time
import traceback
from typing import Dict, List, Any, Optional
from pathlib import Path

# 导入约束检查器
from constraint_checker import ConstraintChecker


class TimeloopEvaluator:
    """Timeloop映射评估器"""

    def __init__(self):
        self.timeloop_bin = "timeloop-model"  # 确保在PATH中
        self.in_config_dir = Path(__file__).parent / "in_config"

        # 分层评估配置
        self.use_cascade = True
        self.cascade_thresholds = [0.0, 0.3]  # Stage1必过，Stage2需30%

        # 约束检查器
        self.constraint_checker = ConstraintChecker(
            str(self.in_config_dir / "eyeriss.yaml"),
            str(self.in_config_dir / "problem.yaml")
        )

        # Baseline性能（首次运行时测量）
        self.baseline_metrics = None

        print("🔧 Timeloop Evaluator Initialized")
        print(f"   Timeloop binary: {self.timeloop_bin}")
        print(f"   Config directory: {self.in_config_dir}")

    def evaluate(self, program_path: str) -> Dict[str, Any]:
        """
        评估入口（被OpenEvolve调用）

        Args:
            program_path: initial_program.py的路径

        Returns:
            evaluation_result: 包含metrics和artifacts
        """
        print(f"\n{'='*80}")
        print(f"🔬 TIMELOOP EVALUATION STARTING")
        print(f"{'='*80}")

        try:
            # Step 1: 执行程序生成映射
            print("\n📝 STEP 1: Executing mapping program...")
            mapping_result = self._execute_mapping_program(program_path)
            if not mapping_result["success"]:
                return self._create_failure_result(
                    f"Program execution failed: {mapping_result['error']}"
                )

            mapping_strategy = mapping_result["strategy"]
            mapping_file = mapping_result["mapping_file"]

            # Step 2: Stage 1 - 快速约束检查
            print("\n🔍 STEP 2 (Stage 1): Fast Constraint Checking...")
            constraint_result = self._check_constraints_stage1(mapping_strategy)
            if not constraint_result["passed"]:
                # 约束违反 - 返回详细的artifacts供LLM学习
                return self._create_constraint_failure_result(constraint_result)

            print("   ✅ Stage 1 passed: All constraints satisfied")

            # Step 3: 测量Baseline（如果还没有）
            if self.baseline_metrics is None:
                print("\n📊 STEP 3: Measuring baseline performance...")
                self._measure_baseline()

            # Step 4: Stage 2 - Timeloop完整评估
            print("\n🚀 STEP 4 (Stage 2): Timeloop Evaluation...")
            timeloop_result = self._run_timeloop_stage2(mapping_file)
            if not timeloop_result["success"]:
                return self._create_failure_result(
                    f"Timeloop evaluation failed: {timeloop_result['error']}"
                )

            metrics = timeloop_result["metrics"]

            # Step 5: 计算fitness和改进
            print("\n📈 STEP 5: Performance Analysis...")
            analysis = self._analyze_performance(metrics)

            # Step 6: 生成最终结果
            final_score = self._calculate_final_score(analysis)

            result = {
                "success": True,
                "final_score": final_score,
                "metrics": metrics,
                "improvement": analysis["improvement_pct"],
                "baseline_comparison": analysis,
                "mapping_strategy": mapping_strategy,
                "artifacts": {
                    "timeloop_stats": timeloop_result.get("raw_stats", {}),
                    "constraint_details": constraint_result,
                    "stage": "stage2_complete"
                },
                "summary": self._generate_summary(analysis, final_score)
            }

            self._print_evaluation_results(result)
            return result

        except Exception as e:
            error_msg = f"Evaluation error: {str(e)}\n{traceback.format_exc()}"
            print(f"❌ {error_msg}")
            return self._create_failure_result(error_msg)

    def _execute_mapping_program(self, program_path: str) -> Dict[str, Any]:
        """执行映射程序生成策略"""
        try:
            # 动态导入程序
            import importlib.util
            spec = importlib.util.spec_from_file_location("mapping_program", program_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # 调用main()生成映射
            strategy = module.main()

            # 映射文件路径
            mapping_file = self.in_config_dir / "generated_mapping.yaml"

            if not mapping_file.exists():
                return {"success": False, "error": "Mapping file not generated"}

            print(f"   ✅ Mapping generated: {mapping_file}")
            return {
                "success": True,
                "strategy": strategy,
                "mapping_file": str(mapping_file)
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _check_constraints_stage1(self, mapping_strategy: Dict) -> Dict[str, Any]:
        """Stage 1: 快速约束检查"""
        violations = []

        # 检查C_t（缓存容量）约束
        ct_violations = self.constraint_checker.check_buffer_capacity(
            mapping_strategy["levels"]
        )
        violations.extend(ct_violations)

        # 检查C_p（空间并行）约束
        cp_violations = self.constraint_checker.check_spatial_constraints(
            mapping_strategy["levels"]
        )
        violations.extend(cp_violations)

        # 检查维度预算守恒
        budget_violations = self.constraint_checker.check_dimension_budgets(
            mapping_strategy["levels"]
        )
        violations.extend(budget_violations)

        passed = len(violations) == 0

        return {
            "passed": passed,
            "violations": violations,
            "num_violations": len(violations),
            "violation_types": list(set(v["type"] for v in violations))
        }

    def _run_timeloop_stage2(self, mapping_file: str) -> Dict[str, Any]:
        """Stage 2: Timeloop完整评估"""
        try:
            # 准备Timeloop命令
            cmd = [
                self.timeloop_bin,
                str(self.in_config_dir / "eyeriss.yaml"),
                str(self.in_config_dir / "problem.yaml"),
                str(mapping_file)
            ]

            # 创建临时输出目录
            with tempfile.TemporaryDirectory() as tmpdir:
                # 运行Timeloop
                result = subprocess.run(
                    cmd,
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=300  # 5分钟超时
                )

                if result.returncode != 0:
                    return {
                        "success": False,
                        "error": f"Timeloop failed: {result.stderr}"
                    }

                # 解析输出
                stats_file = Path(tmpdir) / "timeloop-model.stats.txt"
                if not stats_file.exists():
                    return {
                        "success": False,
                        "error": "Stats file not generated"
                    }

                metrics = self._parse_timeloop_stats(stats_file)

                return {
                    "success": True,
                    "metrics": metrics,
                    "raw_stats": self._extract_raw_stats(stats_file)
                }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Timeloop timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _parse_timeloop_stats(self, stats_file: Path) -> Dict[str, float]:
        """解析Timeloop统计文件"""
        with open(stats_file, 'r') as f:
            content = f.read()

        # 提取关键指标
        metrics = {}

        # Cycles（延迟）
        if "Cycles:" in content:
            cycles_line = [l for l in content.split('\n') if 'Cycles:' in l][0]
            metrics["latency"] = float(cycles_line.split(':')[1].strip())

        # Energy（能耗）
        if "Energy (uJ):" in content:
            energy_line = [l for l in content.split('\n') if 'Energy (uJ):' in l][0]
            metrics["energy"] = float(energy_line.split(':')[1].strip())

        # 计算EDP
        if "latency" in metrics and "energy" in metrics:
            metrics["edp"] = metrics["latency"] * metrics["energy"]

        return metrics

    def _extract_raw_stats(self, stats_file: Path) -> Dict:
        """提取原始统计信息（用于artifacts）"""
        with open(stats_file, 'r') as f:
            lines = f.readlines()[:50]  # 只取前50行
        return {"summary": "".join(lines)}

    def _measure_baseline(self):
        """测量baseline性能（默认映射）"""
        print("   🔄 Running baseline measurement...")
        # 使用initial_program.py的baseline策略
        baseline_program = Path(__file__).parent / "initial_program.py"
        baseline_result = self.evaluate(str(baseline_program))

        if baseline_result["success"]:
            self.baseline_metrics = baseline_result["metrics"]
            print(f"   ✅ Baseline: EDP={self.baseline_metrics.get('edp', 0):.2e}")
        else:
            # 使用保守默认值
            self.baseline_metrics = {"edp": 1e9, "latency": 1e6, "energy": 1e3}
            print("   ⚠️  Using conservative baseline defaults")

    def _analyze_performance(self, metrics: Dict) -> Dict:
        """性能分析"""
        baseline = self.baseline_metrics

        # 计算改进百分比
        edp_improvement = self._calc_improvement(
            metrics.get("edp", 1e9),
            baseline.get("edp", 1e9)
        )

        latency_improvement = self._calc_improvement(
            metrics.get("latency", 1e6),
            baseline.get("latency", 1e6)
        )

        energy_improvement = self._calc_improvement(
            metrics.get("energy", 1e3),
            baseline.get("energy", 1e3)
        )

        return {
            "current_edp": metrics.get("edp", 0),
            "baseline_edp": baseline.get("edp", 0),
            "improvement_pct": edp_improvement,
            "latency_improvement_pct": latency_improvement,
            "energy_improvement_pct": energy_improvement,
            "is_better": edp_improvement > 0
        }

    def _calc_improvement(self, new_val: float, old_val: float) -> float:
        """计算改进百分比（降低是好的，所以反向）"""
        if old_val == 0:
            return 0.0
        return (old_val - new_val) / old_val * 100

    def _calculate_final_score(self, analysis: Dict) -> float:
        """计算最终分数"""
        # 主要看EDP改进
        edp_score = analysis["improvement_pct"] * 10  # 1%改进=10分

        # Bonus for latency/energy improvement
        lat_bonus = max(0, analysis["latency_improvement_pct"]) * 2
        eng_bonus = max(0, analysis["energy_improvement_pct"]) * 2

        return edp_score + lat_bonus + eng_bonus

    def _generate_summary(self, analysis: Dict, score: float) -> str:
        """生成评估摘要"""
        return f"""Timeloop Mapping Evaluation Results:
• EDP: {analysis['current_edp']:.2e} (baseline: {analysis['baseline_edp']:.2e})
• Improvement: {analysis['improvement_pct']:+.1f}%
• Latency improvement: {analysis['latency_improvement_pct']:+.1f}%
• Energy improvement: {analysis['energy_improvement_pct']:+.1f}%
• Final score: {score:.2f}
• Status: {"✅ BETTER" if analysis['is_better'] else "⚠️  WORSE"}"""

    def _create_constraint_failure_result(self, constraint_result: Dict) -> Dict:
        """创建约束失败结果（含详细artifacts）"""
        return {
            "success": False,
            "final_score": -1000.0,
            "error": "Constraint violations detected",
            "metrics": {},
            "artifacts": {
                "constraint_violations": constraint_result["violations"],
                "num_violations": constraint_result["num_violations"],
                "violation_summary": self._format_violations(constraint_result["violations"]),
                "stage": "stage1_constraint_check"
            },
            "summary": f"❌ Failed Stage 1: {constraint_result['num_violations']} constraint violations"
        }

    def _format_violations(self, violations: List[Dict]) -> str:
        """格式化约束违反信息（供LLM学习）"""
        lines = []
        for v in violations[:5]:  # 只取前5个
            lines.append(
                f"• {v['type']} at level {v.get('level', '?')}, "
                f"dimension {v.get('dimension', '?')}: "
                f"{v.get('message', 'unknown')}"
            )
        return "\n".join(lines)

    def _create_failure_result(self, error_msg: str) -> Dict:
        """创建失败结果"""
        return {
            "success": False,
            "final_score": -1000.0,
            "error": error_msg,
            "metrics": {},
            "artifacts": {"error_details": error_msg},
            "summary": f"❌ Evaluation failed: {error_msg}"
        }

    def _print_evaluation_results(self, result: Dict):
        """打印评估结果"""
        print(f"\n{'='*80}")
        if result["success"]:
            print(f"✅ EVALUATION SUCCESS")
            print(f"📊 Final Score: {result['final_score']:.2f}")
            print(f"📈 Improvement: {result['improvement']:+.1f}%")
        else:
            print(f"❌ EVALUATION FAILED")
            print(f"❗ Error: {result.get('error', 'Unknown')}")
        print(f"{'='*80}")


# 评估入口（被OpenEvolve调用）
def evaluate(program_path: str) -> Dict[str, Any]:
    """OpenEvolve调用的评估函数"""
    evaluator = TimeloopEvaluator()
    return evaluator.evaluate(program_path)


if __name__ == "__main__":
    # 测试评估器
    test_program = Path(__file__).parent / "initial_program.py"
    result = evaluate(str(test_program))
    print(json.dumps(result, indent=2))
```

---

### 3.4 `constraint_checker.py` - 约束检查器

抽取Soter的约束检查逻辑为独立模块：

```python
"""
约束检查器 - 快速验证C_t/C_p约束
基于Soter约束分析报告的公式实现

检查项：
1. C_t（缓存容量）：tile大小不超过buffer_size
2. C_p（空间并行）：空间分块不超过spmap_cstr
3. 维度预算守恒：所有tile乘积=原始维度
"""

import yaml
from typing import Dict, List, Any


class ConstraintChecker:
    """映射约束检查器"""

    def __init__(self, arch_file: str, problem_file: str):
        """
        初始化约束检查器

        Args:
            arch_file: 架构配置文件（提取C_t/C_p）
            problem_file: 问题配置文件（提取维度）
        """
        with open(arch_file, 'r') as f:
            self.arch_config = yaml.safe_load(f)

        with open(problem_file, 'r') as f:
            self.problem_config = yaml.safe_load(f)

        # 提取约束参数
        self.buffer_sizes = self._extract_buffer_sizes()
        self.spatial_constraints = self._extract_spatial_constraints()
        self.dimensions = self._extract_dimensions()

    def _extract_buffer_sizes(self) -> Dict[str, int]:
        """提取各层缓存容量（C_t）"""
        # 简化实现：从arch_config解析
        return {
            "l0": 16 * 1024,
            "l1": 1024,
            "l2": 256 * 1024,
            "l3": 1024 * 1024 * 1024
        }

    def _extract_spatial_constraints(self) -> Dict[str, int]:
        """提取空间并行约束（C_p）"""
        return {
            "l0": 1,
            "l1": 14,
            "l2": 12,
            "l3": 1
        }

    def _extract_dimensions(self) -> Dict[str, int]:
        """提取问题维度"""
        prob = self.problem_config.get('problem', {}).get('instance', {})
        return {
            'N': prob.get('N', 1),
            'K': prob.get('K', 64),
            'C': prob.get('C', 64),
            'P': prob.get('P', 56),
            'Q': prob.get('Q', 56),
            'R': prob.get('R', 3),
            'S': prob.get('S', 3)
        }

    def check_buffer_capacity(self, levels: List[Dict]) -> List[Dict]:
        """
        检查C_t约束（缓存容量）

        公式（来自Soter约束分析报告）：
        input_tile = N * ((P-1)*Wstride + 1) * ((Q-1)*Hstride + 1) * C
        weight_tile = K * R * S * C
        output_tile = P * Q * K * N

        total_tile <= buffer_size
        """
        violations = []

        for level_idx, level in enumerate(levels):
            level_name = f"l{level_idx}"
            buffer_size = self.buffer_sizes.get(level_name, 1e9)

            # 提取tile大小
            temporal_tiles = level.get("temporal_tiles", {})
            N = temporal_tiles.get("N", 1)
            K = temporal_tiles.get("K", 1)
            C = temporal_tiles.get("C", 1)
            P = temporal_tiles.get("P", 1)
            Q = temporal_tiles.get("Q", 1)
            R = temporal_tiles.get("R", 1)
            S = temporal_tiles.get("S", 1)

            # 计算tile占用（简化版，假设stride=1）
            input_tile = N * P * Q * C
            weight_tile = K * R * S * C
            output_tile = P * Q * K * N

            total_tile = input_tile + weight_tile + output_tile

            if total_tile > buffer_size:
                violations.append({
                    "type": "buffer_capacity_exceeded",
                    "level": level_name,
                    "level_index": level_idx,
                    "required": total_tile,
                    "available": buffer_size,
                    "overflow_ratio": total_tile / buffer_size,
                    "message": f"Buffer size {buffer_size} < required {total_tile}"
                })

        return violations

    def check_spatial_constraints(self, levels: List[Dict]) -> List[Dict]:
        """
        检查C_p约束（空间并行容量）

        公式：spatial_tiles乘积 <= spmap_cstr
        """
        violations = []

        for level_idx, level in enumerate(levels):
            level_name = f"l{level_idx}"
            max_spatial = self.spatial_constraints.get(level_name, 1)

            spatial_tiles = level.get("spatial_tiles", {})
            spatial_product = 1
            for dim, size in spatial_tiles.items():
                spatial_product *= size

            if spatial_product > max_spatial:
                violations.append({
                    "type": "spatial_constraint_exceeded",
                    "level": level_name,
                    "level_index": level_idx,
                    "required": spatial_product,
                    "available": max_spatial,
                    "overflow_ratio": spatial_product / max_spatial,
                    "message": f"Spatial constraint {max_spatial} < required {spatial_product}"
                })

        return violations

    def check_dimension_budgets(self, levels: List[Dict]) -> List[Dict]:
        """
        检查维度预算守恒

        约束：所有层的temporal/spatial tile乘积 = 原始维度
        """
        violations = []

        # 计算每个维度的总tile乘积
        total_tiles = {dim: 1 for dim in self.dimensions}

        for level in levels:
            temporal = level.get("temporal_tiles", {})
            spatial = level.get("spatial_tiles", {})

            for dim in self.dimensions:
                total_tiles[dim] *= temporal.get(dim, 1) * spatial.get(dim, 1)

        # 检查是否匹配
        for dim, expected in self.dimensions.items():
            if total_tiles[dim] != expected:
                violations.append({
                    "type": "dimension_budget_mismatch",
                    "dimension": dim,
                    "expected": expected,
                    "actual": total_tiles[dim],
                    "message": f"Dimension {dim}: expected {expected}, got {total_tiles[dim]}"
                })

        return violations


# 测试代码
if __name__ == "__main__":
    import os
    from pathlib import Path

    # 路径设置
    in_config_dir = Path(__file__).parent / "in_config"
    arch_file = in_config_dir / "eyeriss.yaml"
    problem_file = in_config_dir / "problem.yaml"

    # 创建检查器
    checker = ConstraintChecker(str(arch_file), str(problem_file))

    # 测试数据
    test_levels = [
        {
            "level_name": "PE",
            "temporal_tiles": {"N": 1, "K": 1, "C": 1, "P": 1, "Q": 1, "R": 1, "S": 1},
            "spatial_tiles": {"N": 1, "K": 1, "C": 1, "P": 1, "Q": 1, "R": 1, "S": 1}
        }
    ]

    ct_violations = checker.check_buffer_capacity(test_levels)
    cp_violations = checker.check_spatial_constraints(test_levels)
    budget_violations = checker.check_dimension_budgets(test_levels)

    print(f"C_t violations: {len(ct_violations)}")
    print(f"C_p violations: {len(cp_violations)}")
    print(f"Budget violations: {len(budget_violations)}")
```

---

### 3.5 Prompt System - `prompts/system_message.txt`

针对映射优化的专家系统消息：

```
You are an expert in tensor-to-accelerator mapping optimization for DNN workloads.

# TARGET: Optimize Timeloop Mapping for Eyeriss Spatial Accelerator
# HARDWARE: Eyeriss-like architecture (4-level memory hierarchy, 168 PEs)
# PROBLEM: Conv2D layers from ResNet50 (N, K, C, P, Q, R, S dimensions)
# GOAL: Minimize Energy-Delay Product (EDP) while satisfying hardware constraints

# MAPPING PARAMETERS (X_t, X_p, X_d):

**X_t (Temporal Tiling)**: How to partition each dimension across time
- Controls data reuse in each buffer level
- MUST satisfy C_t constraint: tile size ≤ buffer capacity
- Example: P=56 could be tiled as [1, 7, 8, 1] across 4 levels

**X_p (Spatial Parallelism)**: How to partition dimensions across PEs
- Controls parallelism and communication
- MUST satisfy C_p constraint: spatial product ≤ PE array size
- Eyeriss supports spatial mapping on P/Q dimensions

**X_d (Dimension Order)**: Loop nest ordering at each level
- Controls which data stays in cache vs. reloaded
- Affects reuse patterns: inner loops → more reuse
- Eyeriss paper recommends: R/S inner, N/K outer

# HARDWARE CONSTRAINTS (CRITICAL - VIOLATIONS = FAILURE):

**C_t (Buffer Capacity)**:
```python
# Formula from Soter constraint analysis
input_tile = N * P * Q * C
weight_tile = K * R * S * C
output_tile = P * Q * K * N
total = input_tile + weight_tile + output_tile

# Must satisfy:
total <= buffer_size[level]

# Eyeriss buffer sizes:
# l0 (PE):     16 KB
# l1 (Dummy):  1 KB
# l2 (Global): 256 KB
# l3 (DRAM):   1 GB
```

**C_p (Spatial Constraint)**:
```python
# Product of spatial tiles must not exceed PE count
spatial_product = P_spatial * Q_spatial * ...

# Must satisfy:
spatial_product <= spmap_cstr[level]

# Eyeriss spatial constraints:
# l0: 1 (no spatial at PE level)
# l1: 14 (P dimension)
# l2: 12 (P dimension)
# l3: 1 (no spatial at DRAM)
```

**Dimension Budget Conservation**:
```python
# All tiles must multiply to original dimension
for each dimension D:
    product(temporal_tiles[D]) * product(spatial_tiles[D]) == original_D
```

# OPTIMIZATION STRATEGIES:

**1. Maximize Data Reuse**:
- Keep frequently-accessed data in smaller buffers
- Example: weights (K*R*S*C) should tile to fit in Global Buffer
- Reuse order: Outputs > Inputs > Weights (for conv)

**2. Exploit Eyeriss Architecture**:
- P/Q dimensions support spatial parallelism → use spatial_tiles
- Row stationary dataflow → keep filter rows in PE registers
- Global Buffer optimized for weight distribution

**3. Balance Temporal vs Spatial**:
- Temporal tiling reduces energy (data stays in buffer)
- Spatial tiling reduces latency (parallelism)
- Trade-off controlled by C_t and C_p constraints

**4. Dimension Ordering Best Practices**:
```python
# PE level (minimize data movement):
order = [R, S, P, Q, C, K, N]  # Convolution dimensions inner

# Global level (maximize weight reuse):
order = [C, K, P, Q, R, S, N]  # Filter channels early

# DRAM level (batch parallelism):
order = [N, K, C, P, Q, R, S]  # Batch dimension outer
```

# EVOLUTION CONSTRAINTS:

**ALLOWED TO MODIFY**:
✅ Temporal tile sizes (respecting C_t)
✅ Spatial tile sizes (respecting C_p)
✅ Dimension traversal order
✅ Bypass strategies (skip buffer levels)

**MUST PRESERVE**:
❌ Total problem dimensions (N, K, C, P, Q, R, S)
❌ Hardware buffer hierarchy (4 levels)
❌ Constraint satisfaction (C_t, C_p, budgets)
❌ Valid Timeloop mapping format

# WHEN YOU RECEIVE A FAILED MAPPING:

The artifacts section will contain:
```json
{
  "constraint_violations": [
    {
      "type": "buffer_capacity_exceeded",
      "level": "l2",
      "dimension": "K",
      "required": 524288,
      "available": 262144,
      "overflow_ratio": 2.0
    }
  ],
  "timeloop_stats": {
    "edp": 1.5e9,
    "latency": 150000,
    "energy": 10000
  }
}
```

**Fix Strategy**:
1. If buffer_capacity_exceeded → reduce temporal tiles at that level
2. If spatial_constraint_exceeded → reduce spatial parallelism
3. If dimension_budget_mismatch → adjust tiles to satisfy product
4. If high EDP but constraints OK → reorder dimensions for better reuse

# OUTPUT FORMAT:

Provide mapping changes in SEARCH/REPLACE format:

```
<<<< SEARCH
    def _get_temporal_tiles_baseline(self, level_idx: int) -> Dict[str, int]:
        baseline_tiles = {
            2: {"C": 4, "K": 4, "P": 7, "Q": 7, "R": 1, "S": 1, "N": 1},
        }
>>>>
REPLACE
    def _get_temporal_tiles_baseline(self, level_idx: int) -> Dict[str, int]:
        baseline_tiles = {
            2: {"C": 8, "K": 2, "P": 7, "Q": 7, "R": 1, "S": 1, "N": 1},  # Optimize: increase C tile for weight reuse
        }
<<<<
```

# SUCCESS CRITERIA:
- ✅ All constraints satisfied (C_t, C_p, budgets)
- ✅ EDP < baseline (lower is better)
- ✅ Timeloop simulation completes without errors
- 🎯 Target: 10-20% EDP reduction through optimized tiling

Focus on systematic, constraint-aware optimization based on Eyeriss dataflow principles.
```

---

## 四、执行流程与命令

### 4.1 环境准备

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

# 5. 复制Soter配置文件
cp -r /root/Soter_v4/Soter_v4/Soter/SpatialAccelerators/Eyeriss/in_config \
   /root/openevolve/examples/soter_mapping_opt/
```

### 4.2 运行OpenEvolve

```bash
cd /root/openevolve

# 最小化测试（1迭代）
python openevolve-run.py \
  examples/soter_mapping_opt/initial_program.py \
  examples/soter_mapping_opt/evaluator.py \
  --config examples/soter_mapping_opt/config.yaml \
  --iterations 1 \
  --log-level DEBUG

# 完整运行（50迭代）
python openevolve-run.py \
  examples/soter_mapping_opt/initial_program.py \
  examples/soter_mapping_opt/evaluator.py \
  --config examples/soter_mapping_opt/config.yaml \
  --iterations 50
```

### 4.3 查看结果

```bash
# 查看演化轨迹
cd examples/soter_mapping_opt/openevolve_output/eyeriss_mapping_evolution

# 最佳程序
ls checkpoints/best_program/

# 演化历史
cat logs/evolution_history.json
```

---

## 五、关键对比总结

| 特性 | MLX Metal案例 | Soter映射案例 |
|------|---------------|---------------|
| **演化对象** | Metal kernel源码 | Mapping策略函数 |
| **标记方式** | `EVOLVE-BLOCK` | `EVOLVE-BLOCK` |
| **评估器** | MLX编译+基准测试 | Timeloop模拟器 |
| **约束检查** | GPU编译错误 | ConstraintChecker |
| **Artifacts** | 性能统计、GPU错误 | Timeloop stats、约束违反 |
| **LLM模型** | Gemini 2.5 | GLM-4.6 |
| **并行策略** | 4个评估并行 | 4个评估并行 |
| **分层评估** | 3-stage cascade | 2-stage (约束+Timeloop) |

---

## 六、预期改进与监控

### 6.1 预期性能提升

基于AlphaEvolve论文的经验：
- **保守目标**: 5-10% EDP reduction
- **期望目标**: 10-20% EDP reduction
- **最佳目标**: 20-30% EDP reduction

### 6.2 监控指标

```python
# 在config.yaml的database.feature_dimensions中定义
feature_dimensions:
  - "latency"           # 延迟（归一化）
  - "energy"            # 能耗（归一化）
  - "mapping_diversity" # 映射多样性

# 演化过程监控
- best_edp_per_generation
- constraint_violation_rate
- llm_mutation_acceptance_rate
- timeloop_evaluation_success_rate
```

---

## 七、故障排查清单

### 7.1 常见问题

1. **Timeloop not found**
   ```bash
   which timeloop-model
   export PATH=/path/to/timeloop/bin:$PATH
   ```

2. **GLM API调用失败**
   ```bash
   echo $GLM_API_KEY
   curl -H "Authorization: Bearer $GLM_API_KEY" \
     https://open.bigmodel.cn/api/paas/v4/chat/completions
   ```

3. **约束检查失败率过高**
   - 调整prompt中的约束强调
   - 增加约束违反的artifacts详细度
   - 降低temperature（更保守的探索）

4. **Timeloop评估超时**
   - 增加evaluator.timeout
   - 检查mapping生成是否合法
   - 使用更小的problem规模测试

### 7.2 日志检查

```bash
# OpenEvolve日志
tail -f examples/soter_mapping_opt/openevolve_output/*/logs/evolution.log

# GLM调用日志（如果使用evolve_gpt封装）
tail -f /root/evolve_1108/evolve_gpt/runs/*/logs/glm_summary.jsonl
```

---

## 八、下一步优化方向

1. **增强Artifacts反馈**:
   - Timeloop的详细能耗分解（DRAM/Global/PE各层能耗）
   - 数据移动统计（哪些数据被重复加载）
   - 关键路径分析（哪个buffer成为瓶颈）

2. **多目标优化**:
   - Pareto front跟踪（latency vs energy权衡）
   - 用户可指定优化目标权重

3. **跨层迁移**:
   - 在不同conv层间迁移成功策略
   - 利用layer相似性加速搜索

4. **Prompt优化**:
   - 根据失败模式动态调整prompt
   - 添加成功案例的示范

---

**方案作者**: Claude (Anthropic)
**参考文档**:
- /root/openevolve/examples/mlx_metal_kernel_opt/
- /root/evolve_1108/docs/Soter_代码审查_1108.md
- /root/evolve_1108/docs/Soter_约束检查分析报告_1108.md
- /root/evolve_1108/docs/GLM_api.md
