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
        # 避免递归: 如果已经在测量baseline,使用保守默认值
        if hasattr(self, '_measuring_baseline') and self._measuring_baseline:
            print("   ⚠️  Recursive baseline call detected, using conservative defaults")
            self.baseline_metrics = {"edp": 1e12, "latency": 1e7, "energy": 1e5}
            return

        self._measuring_baseline = True
        print("   🔄 Running baseline measurement...")

        try:
            # 使用initial_program.py的baseline策略
            baseline_program = Path(__file__).parent / "initial_program.py"

            # 直接运行timeloop评估,不递归调用evaluate()
            mapping_result = self._execute_mapping_program(str(baseline_program))
            if not mapping_result["success"]:
                self.baseline_metrics = {"edp": 1e12, "latency": 1e7, "energy": 1e5}
                print("   ⚠️  Baseline program failed, using conservative defaults")
                return

            timeloop_result = self._run_timeloop_stage2(mapping_result["mapping_file"])
            if timeloop_result["success"]:
                self.baseline_metrics = timeloop_result["metrics"]
                print(f"   ✅ Baseline: EDP={self.baseline_metrics.get('edp', 0):.2e}")
            else:
                self.baseline_metrics = {"edp": 1e12, "latency": 1e7, "energy": 1e5}
                print("   ⚠️  Timeloop failed, using conservative defaults")
        finally:
            self._measuring_baseline = False

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


# ============================================
# OpenEvolve Cascade Evaluation Stage Functions
# ============================================

def evaluate_stage1(program_path: str) -> Dict[str, Any]:
    """
    Stage 1: 快速约束检查 (OpenEvolve cascade evaluation调用)

    这个函数会被OpenEvolve的cascade evaluation系统调用。
    约束通过返回stage1_passed=1.0,失败返回0.0。

    Args:
        program_path: initial_program.py的路径

    Returns:
        {
            "metrics": {"stage1_passed": float},  # 1.0=通过, 0.0=失败
            "artifacts": {...}  # 约束违反详情(如果有)
        }
    """
    evaluator = TimeloopEvaluator()

    try:
        # Step 1: 执行程序生成映射
        mapping_result = evaluator._execute_mapping_program(program_path)
        if not mapping_result["success"]:
            return {
                "metrics": {"stage1_passed": 0.0},
                "artifacts": {
                    "stage": "program_execution",
                    "error": mapping_result["error"]
                }
            }

        # Step 2: 约束检查
        mapping_strategy = mapping_result["strategy"]
        constraint_result = evaluator._check_constraints_stage1(mapping_strategy)

        if constraint_result["passed"]:
            # 约束通过 - 返回stage1_passed=1.0以进入Stage2
            return {
                "metrics": {"stage1_passed": 1.0},
                "artifacts": {
                    "stage": "stage1_constraint_check",
                    "num_violations": 0,
                    "message": "All constraints satisfied"
                }
            }
        else:
            # 约束失败 - 返回详细的artifacts供LLM学习
            return {
                "metrics": {"stage1_passed": 0.0},
                "artifacts": {
                    "stage": "stage1_constraint_check",
                    "constraint_violations": constraint_result["violations"],
                    "num_violations": constraint_result["num_violations"],
                    "violation_summary": evaluator._format_violations(constraint_result["violations"]),
                    "violation_types": constraint_result["violation_types"]
                }
            }

    except Exception as e:
        print(f"❌ Stage1 evaluation error: {str(e)}")
        traceback.print_exc()
        return {
            "metrics": {"stage1_passed": 0.0},
            "artifacts": {
                "stage": "stage1_error",
                "error": str(e),
                "traceback": traceback.format_exc()
            }
        }


def evaluate_stage2(program_path: str) -> Dict[str, Any]:
    """
    Stage 2: Timeloop完整评估 (OpenEvolve cascade evaluation调用)

    只有通过Stage1的程序才会到这里。
    返回性能指标,其中latency和energy用于MAP-Elites的feature_dimensions。

    Args:
        program_path: initial_program.py的路径

    Returns:
        {
            "metrics": {
                "latency": float,    # ← 用于feature_dimensions
                "energy": float,     # ← 用于feature_dimensions
                "edp": float,        # ← 用于fitness计算
                "stage2_passed": 1.0
            },
            "artifacts": {...}  # Timeloop详细统计
        }
    """
    evaluator = TimeloopEvaluator()

    try:
        # Step 1: 重新执行程序(因为是新进程)
        mapping_result = evaluator._execute_mapping_program(program_path)
        if not mapping_result["success"]:
            return {
                "metrics": {"stage2_passed": 0.0, "error": 0.0},
                "artifacts": {
                    "stage": "stage2_program_execution",
                    "error": mapping_result["error"]
                }
            }

        # Step 2: Timeloop评估
        mapping_file = mapping_result["mapping_file"]
        timeloop_result = evaluator._run_timeloop_stage2(mapping_file)

        if not timeloop_result["success"]:
            return {
                "metrics": {"stage2_passed": 0.0, "error": 0.0},
                "artifacts": {
                    "stage": "stage2_timeloop_evaluation",
                    "error": timeloop_result["error"]
                }
            }

        # Step 3: 提取指标
        metrics = timeloop_result["metrics"]

        # 返回格式化的结果
        return {
            "metrics": {
                # 用于MAP-Elites的feature_dimensions
                "latency": metrics["latency"],
                "energy": metrics["energy"],
                # 用于fitness计算(get_fitness_score会排除feature_dimensions)
                "edp": metrics["edp"],
                # Stage2通过标记
                "stage2_passed": 1.0
            },
            "artifacts": {
                "stage": "stage2_complete",
                "timeloop_stats": timeloop_result.get("raw_stats", {}),
                "latency": metrics["latency"],
                "energy": metrics["energy"],
                "edp": metrics["edp"]
            }
        }

    except Exception as e:
        print(f"❌ Stage2 evaluation error: {str(e)}")
        traceback.print_exc()
        return {
            "metrics": {"stage2_passed": 0.0, "error": 0.0},
            "artifacts": {
                "stage": "stage2_error",
                "error": str(e),
                "traceback": traceback.format_exc()
            }
        }


if __name__ == "__main__":
    # 测试评估器
    test_program = Path(__file__).parent / "initial_program.py"

    print("\n" + "="*80)
    print("Testing Cascade Evaluation")
    print("="*80)

    # 测试Stage1
    print("\n🔍 Testing Stage 1...")
    stage1_result = evaluate_stage1(str(test_program))
    print(f"Stage1 passed: {stage1_result['metrics'].get('stage1_passed', 0.0)}")
    if stage1_result['metrics'].get('stage1_passed', 0.0) > 0:
        print("✅ Stage 1 passed")

        # 测试Stage2
        print("\n🚀 Testing Stage 2...")
        stage2_result = evaluate_stage2(str(test_program))
        print(f"Stage2 passed: {stage2_result['metrics'].get('stage2_passed', 0.0)}")
        if stage2_result['metrics'].get('stage2_passed', 0.0) > 0:
            print("✅ Stage 2 passed")
            print(f"   Latency: {stage2_result['metrics'].get('latency', 0)}")
            print(f"   Energy:  {stage2_result['metrics'].get('energy', 0)}")
            print(f"   EDP:     {stage2_result['metrics'].get('edp', 0)}")

    # 也测试直接evaluate()
    print("\n🔬 Testing direct evaluate()...")
    result = evaluate(str(test_program))
    print(json.dumps(result, indent=2))
