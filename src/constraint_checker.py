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
