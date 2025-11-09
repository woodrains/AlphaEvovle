"""
New Evaluator for Separated Architecture
=========================================

使用新架构：algorithm.py → timeloop_interface.py → 统一metrics

关键改进：
1. 只评估algorithm.py（LLM专注于算法）
2. 通过timeloop_interface.py处理Timeloop交互
3. 返回统一的combined_score作为主fitness
4. 保留latency/energy作为feature_dimensions

评估流程：
Stage 1: 快速约束检查（通过TimeloopInterface）
Stage 2: Timeloop完整评估 + combined_score计算
"""

import os
import sys
import json
import importlib.util
import traceback
from typing import Dict, Any
from pathlib import Path

# 导入TimeloopInterface
from timeloop_interface import TimeloopInterface


class AlgorithmEvaluator:
    """算法评估器 - 专注于algorithm.py的评估"""

    def __init__(self, program_id: str = None):
        # Timeloop接口 - CRITICAL FIX: Pass program_id for unique output directories
        config_dir = "/root/evolve_1108/cc_1108/config/timeloop"
        self.timeloop_interface = TimeloopInterface(config_dir, program_id=program_id)
        self.program_id = program_id

        # Baseline性能（用于计算combined_score）
        self.baseline_edp = None
        self._measure_baseline()

        print("🔧 Algorithm Evaluator Initialized (New Architecture)")
        print(f"   Config directory: {config_dir}")
        print(f"   Program ID: {program_id if program_id else 'None (serial mode)'}")
        print(f"   Baseline EDP: {self.baseline_edp:.2e}" if self.baseline_edp else "   Baseline: Not measured")

    def _measure_baseline(self):
        """测量baseline性能"""
        try:
            print("📊 Measuring baseline performance...")

            # 使用initial_program.py作为baseline
            baseline_program = "/root/evolve_1108/cc_1108/src/initial_program.py"

            # 执行baseline程序
            spec = importlib.util.spec_from_file_location("baseline", baseline_program)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # 生成mapping
            strategy = module.main()

            # 转换并运行Timeloop
            mapping_file = self.timeloop_interface.convert_to_mapping({"levels": strategy["levels"]})
            stats = self.timeloop_interface.run_timeloop(mapping_file)

            if stats.get("success", False):
                self.baseline_edp = stats["edp"]
                print(f"   ✅ Baseline measured: EDP={self.baseline_edp:.2e}")
            else:
                # 保守默认值
                self.baseline_edp = 1e12
                print("   ⚠️  Baseline measurement failed, using conservative default")

        except Exception as e:
            print(f"   ⚠️  Baseline measurement error: {e}")
            self.baseline_edp = 1e12

    def evaluate_algorithm(self, algorithm_path: str) -> Dict[str, Any]:
        """
        评估algorithm.py

        Args:
            algorithm_path: algorithm.py的路径

        Returns:
            evaluation_result: 包含metrics和artifacts
        """
        try:
            # Step 1: 动态导入algorithm.py
            print("\n📝 Step 1: Loading algorithm...")
            spec = importlib.util.spec_from_file_location("algorithm", algorithm_path)
            algo_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(algo_module)

            # Step 2: 调用算法生成决策
            print("🧠 Step 2: Generating mapping decisions...")
            decisions = algo_module.generate_mapping_decisions(
                problem_dims=self.timeloop_interface.problem_dims,
                buffer_levels=self.timeloop_interface.buffer_levels,
                buffer_sizes=self.timeloop_interface.buffer_sizes,
                spatial_constraints=self.timeloop_interface.spatial_constraints
            )

            # Step 3: 约束检查（Stage 1）
            print("🔍 Step 3 (Stage 1): Constraint validation...")
            is_valid, violations = self.timeloop_interface.validate_decisions(decisions)

            if not is_valid:
                # 约束违反 - 返回失败结果
                return self._create_constraint_failure_result(violations)

            print("   ✅ All constraints satisfied")

            # Step 4: 转换为Timeloop mapping
            print("🔄 Step 4: Converting to Timeloop format...")
            mapping_file = self.timeloop_interface.convert_to_mapping(decisions)
            print(f"   ✅ Mapping file: {mapping_file}")

            # Step 5: 运行Timeloop仿真（Stage 2）
            print("🚀 Step 5 (Stage 2): Running Timeloop simulation...")
            stats = self.timeloop_interface.run_timeloop(mapping_file)

            if not stats.get("success", False):
                return {
                    "metrics": {
                        "combined_score": -1000.0,
                        "edp": float('inf'),
                        "latency": 0,
                        "energy": 0
                    },
                    "artifacts": {
                        "stage": "timeloop_execution_failed",
                        "error": stats.get("error", "Unknown error")
                    }
                }

            # Step 6: 计算combined_score
            print("📈 Step 6: Calculating combined_score...")
            edp = stats["edp"]
            latency = stats["latency"]
            energy = stats["energy"]

            print(f"   Timeloop Results:")
            print(f"     • Latency: {latency:,} cycles")
            print(f"     • Energy: {energy:.2f} uJ")
            print(f"     • EDP: {edp:.2e}")

            # combined_score设计：
            # - 目标：最小化EDP
            # - Fitness = -EDP (越小的EDP → 越大的score)
            # - 归一化：相对于baseline的改进百分比 × 100
            improvement_pct = 0.0
            if self.baseline_edp and self.baseline_edp > 0:
                improvement_pct = (self.baseline_edp - edp) / self.baseline_edp * 100
                combined_score = improvement_pct  # 正值=改进，负值=退化
            else:
                # 如果没有baseline，直接使用负EDP
                combined_score = -edp / 1e9  # 归一化到合理范围

            print(f"   Baseline EDP: {self.baseline_edp if self.baseline_edp else 0:.2e}")
            print(f"   Combined Score: {combined_score:.2f} (improvement: {improvement_pct:.1f}%)")

            # Step 7: 返回统一的metrics结构
            return {
                "metrics": {
                    "combined_score": combined_score,  # ← OpenEvolve的主fitness
                    "edp": edp,                        # ← 用于分析
                    "latency": latency,                # ← feature dimension
                    "energy": energy                   # ← feature dimension
                },
                "artifacts": {
                    "stage": "evaluation_complete",
                    "timeloop_stats": {
                        "edp": edp,
                        "latency": latency,
                        "energy": energy
                    },
                    "mapping_decisions": decisions,
                    "baseline_edp": self.baseline_edp,
                    "improvement_pct": improvement_pct if self.baseline_edp else 0
                }
            }

        except Exception as e:
            error_msg = f"Evaluation error: {str(e)}\n{traceback.format_exc()}"
            print(f"❌ {error_msg}")
            return {
                "metrics": {
                    "combined_score": -1000.0,
                    "edp": float('inf'),
                    "latency": 0,
                    "energy": 0
                },
                "artifacts": {
                    "stage": "evaluation_error",
                    "error": error_msg
                }
            }

    def _create_constraint_failure_result(self, violations: list) -> Dict:
        """创建约束失败结果"""
        violation_summary = "\n".join([
            f"• {v['type']}: {v['message']}"
            for v in violations[:5]  # 只显示前5个
        ])

        return {
            "metrics": {
                "combined_score": -1000.0,  # 约束失败给予惩罚分数
                "edp": float('inf'),
                "latency": 0,
                "energy": 0
            },
            "artifacts": {
                "stage": "constraint_check_failed",
                "constraint_violations": violations,
                "num_violations": len(violations),
                "violation_summary": violation_summary,
                "violation_types": list(set(v["type"] for v in violations))
            }
        }


# ============================================
# OpenEvolve Evaluation Entry Points
# ============================================

def evaluate(algorithm_path: str) -> Dict[str, Any]:
    """
    统一评估入口（被OpenEvolve调用）

    Args:
        algorithm_path: algorithm.py的路径

    Returns:
        {
            "metrics": {
                "combined_score": float,  # ← OpenEvolve的主fitness
                "edp": float,             # ← 用于分析
                "latency": float,         # ← feature dimension
                "energy": float           # ← feature dimension
            },
            "artifacts": {...}
        }
    """
    # CRITICAL FIX: Extract unique program ID from temp file path to avoid parallel file races
    import os
    program_id = os.path.basename(algorithm_path).replace('.py', '')  # Use filename as unique ID

    evaluator = AlgorithmEvaluator(program_id=program_id)
    return evaluator.evaluate_algorithm(algorithm_path)


def evaluate_stage1(algorithm_path: str) -> Dict[str, Any]:
    """
    Stage 1: 快速约束检查

    Returns:
        {
            "metrics": {"stage1_passed": 1.0 or 0.0},
            "artifacts": {...}
        }
    """
    # CRITICAL FIX: Extract unique program ID from temp file path
    import os
    program_id = os.path.basename(algorithm_path).replace('.py', '')

    evaluator = AlgorithmEvaluator(program_id=program_id)

    try:
        # 导入algorithm
        spec = importlib.util.spec_from_file_location("algorithm", algorithm_path)
        algo_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(algo_module)

        # 生成决策
        decisions = algo_module.generate_mapping_decisions(
            problem_dims=evaluator.timeloop_interface.problem_dims,
            buffer_levels=evaluator.timeloop_interface.buffer_levels,
            buffer_sizes=evaluator.timeloop_interface.buffer_sizes,
            spatial_constraints=evaluator.timeloop_interface.spatial_constraints
        )

        # 约束检查
        is_valid, violations = evaluator.timeloop_interface.validate_decisions(decisions)

        if is_valid:
            return {
                "metrics": {
                    "stage1_passed": 1.0,
                    "combined_score": 1.0  # Placeholder to pass cascade threshold
                },
                "artifacts": {
                    "stage": "stage1_constraint_check",
                    "num_violations": 0,
                    "message": "All constraints satisfied"
                }
            }
        else:
            violation_summary = "\n".join([
                f"• {v['type']}: {v['message']}" for v in violations[:5]
            ])
            return {
                "metrics": {
                    "stage1_passed": 0.0,
                    "combined_score": -1000.0  # Failure score
                },
                "artifacts": {
                    "stage": "stage1_constraint_check",
                    "constraint_violations": violations,
                    "num_violations": len(violations),
                    "violation_summary": violation_summary,
                    "violation_types": list(set(v["type"] for v in violations))
                }
            }

    except Exception as e:
        print(f"❌ Stage1 error: {e}")
        traceback.print_exc()
        return {
            "metrics": {
                "stage1_passed": 0.0,
                "combined_score": -1000.0  # Failure score
            },
            "artifacts": {
                "stage": "stage1_error",
                "error": str(e),
                "traceback": traceback.format_exc()
            }
        }


def evaluate_stage2(algorithm_path: str) -> Dict[str, Any]:
    """
    Stage 2: Timeloop完整评估

    Returns:
        {
            "metrics": {
                "combined_score": float,
                "latency": float,
                "energy": float,
                "edp": float,
                "stage2_passed": 1.0
            },
            "artifacts": {...}
        }
    """
    # Stage2直接调用完整评估
    result = evaluate(algorithm_path)

    # 添加stage2_passed标记
    if result["metrics"]["combined_score"] > -1000:
        result["metrics"]["stage2_passed"] = 1.0
    else:
        result["metrics"]["stage2_passed"] = 0.0

    return result


# ============================================
# 测试接口
# ============================================

if __name__ == "__main__":
    print("\n" + "="*80)
    print("Testing New Architecture Evaluator")
    print("="*80)

    # 测试algorithm.py
    test_algorithm = "/root/evolve_1108/cc_1108/src/algorithm.py"

    print("\n🔍 Testing Stage 1...")
    stage1_result = evaluate_stage1(test_algorithm)
    print(f"Stage1 passed: {stage1_result['metrics'].get('stage1_passed', 0.0)}")

    if stage1_result['metrics'].get('stage1_passed', 0.0) > 0:
        print("✅ Stage 1 passed")

        print("\n🚀 Testing Stage 2 (Full Evaluation)...")
        result = evaluate(test_algorithm)

        print("\n📊 Results:")
        print(json.dumps(result["metrics"], indent=2))
        print(f"\nCombined Score: {result['metrics']['combined_score']:.2f}")
        print(f"EDP: {result['metrics']['edp']:.2e}")
        print(f"Latency: {result['metrics']['latency']}")
        print(f"Energy: {result['metrics']['energy']}")
