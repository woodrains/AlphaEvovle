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
        # Eyeriss实际的buffer层级（从内到外）
        # PE level包含3个独立的RegFile
        # 匹配eyeriss.yaml中定义的实际buffer名称
        return [
            "PsumRegFile",      # PE level - partial sums (outputs)
            "WeightRegFile",    # PE level - weights
            "InputRegFile",     # PE level - inputs (activations)
            "DummyBuffer",      # Level 1 - pass-through buffer
            "GlobalBuffer",     # Level 2 - shared SRAM
            "DRAM"              # Level 3 - main memory
        ]

    def _parse_buffer_sizes(self) -> Dict[str, int]:
        """解析各层缓存容量（C_t约束）"""
        # 从eyeriss.yaml中提取实际buffer大小
        # 计算公式: depth * width * word-bits / 8 (转换为字节)
        return {
            "InputRegFile": 3 * 64 * 16 // 8,           # 3 * 64 * 16bits = 384 bytes
            "WeightRegFile": 48 * 64 * 16 // 8,         # 48 * 64 * 16bits = 6144 bytes
            "PsumRegFile": 4 * 64 * 16 // 8,            # 4 * 64 * 16bits = 512 bytes
            "DummyBuffer": 0,                            # depth=0, pass-through
            "GlobalBuffer": 32768 * 64 * 16 // 8,       # 32768 * 64 * 16bits = 4MB
            "DRAM": 1024 * 1024 * 1024                   # 1GB (unlimited)
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
        # Baseline: 固定顺序（从内到外：PE → Dummy → Global → DRAM）
        baseline_orders = {
            0: ["R", "S", "P", "Q", "C", "K", "N"],  # PE层(最内)
            1: ["P", "Q", "R", "S", "C", "K", "N"],  # Dummy层
            2: ["C", "K", "P", "Q", "R", "S", "N"],  # Global层
            3: ["N", "K", "C", "P", "Q", "R", "S"]   # DRAM层(最外)
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
        # 更合理的baseline: 根据层级分配不同的tile
        # 确保维度预算守恒: Π(all levels) = original dimension

        level_names = ["PsumRegFile", "WeightRegFile", "InputRegFile", "DummyBuffer", "GlobalBuffer", "DRAM"]
        level_name = level_names[level_idx]

        # PE level RegFiles: 只保留小的tile (S维度)
        if level_name == "PsumRegFile":
            return {'N': 1, 'K': 1, 'C': 1, 'P': 1, 'Q': 1, 'R': 1, 'S': 3}
        elif level_name == "WeightRegFile":
            return {'N': 1, 'K': 1, 'C': 1, 'P': 1, 'Q': 1, 'R': 3, 'S': 1}
        elif level_name == "InputRegFile":
            return {'N': 1, 'K': 1, 'C': 1, 'P': 1, 'Q': 1, 'R': 1, 'S': 1}

        # DummyBuffer: pass-through
        elif level_name == "DummyBuffer":
            return {'N': 1, 'K': 1, 'C': 1, 'P': 1, 'Q': 1, 'R': 1, 'S': 1}

        # GlobalBuffer: 保留中等tile (P, Q的一部分)
        elif level_name == "GlobalBuffer":
            return {'N': 1, 'K': 4, 'C': 1, 'P': 7, 'Q': 8, 'R': 1, 'S': 1}

        # DRAM: 剩余的所有dimension
        elif level_name == "DRAM":
            # 计算剩余的dimension (原始/所有前面层的乘积)
            remaining = {}
            for dim in self.dimensions:
                original = self.dimensions[dim]
                # 简化: 直接计算剩余
                if dim == 'N':
                    remaining[dim] = original  # 1
                elif dim == 'K':
                    remaining[dim] = original // 4  # 32/4=8
                elif dim == 'C':
                    remaining[dim] = original  # 3
                elif dim == 'P':
                    remaining[dim] = original // 7  # 224/7=32
                elif dim == 'Q':
                    remaining[dim] = original // 8  # 224/8=28
                elif dim == 'R':
                    remaining[dim] = original // 3  # 3/3=1
                elif dim == 'S':
                    remaining[dim] = original // 3  # 3/3=1
            return remaining

        # Default: all 1
        return {dim: 1 for dim in self.dimensions}

    def _get_spatial_tiles_baseline(self, level_idx: int) -> Dict[str, int]:
        """
        BASELINE: 空间并行分块（X_p参数）

        优化方向（供LLM参考）：
        - 需满足C_p约束（空间并行容量）
        - 空间并行可减少延迟，但受硬件限制
        - Eyeriss支持P/Q维度的空间展开
        """
        # Baseline: 全部spatial=1 (无空间并行,最保守)
        # 这确保C_p约束满足,且维度预算守恒
        return {dim: 1 for dim in self.dimensions}

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
            level_name = level_strategy["level_name"]

            # 1. Temporal mapping (必需)
            factors_str = " ".join([
                f"{dim}={size}"
                for dim, size in level_strategy["temporal_tiles"].items()
            ])
            perm_str = "".join(level_strategy["dimension_order"])  # 无空格,如"RSPQNKC"

            temporal_mapping = {
                "target": level_name,
                "type": "temporal",
                "factors": factors_str,
                "permutation": perm_str
            }
            mapping["mapping"].append(temporal_mapping)

            # 2. Datatype bypass mapping (为每层添加)
            # 根据buffer类型决定keep哪些数据类型
            datatype_mapping = {
                "target": level_name,
                "type": "datatype"
            }

            # 根据level和bypass策略设置keep/bypass
            bypass_list = level_strategy.get("bypass", [])
            if not bypass_list:
                # 默认策略: PE level RegFiles各自keep自己的数据类型
                if level_name == "PsumRegFile":
                    datatype_mapping["keep"] = ["Outputs"]
                    datatype_mapping["bypass"] = ["Weights", "Inputs"]
                elif level_name == "WeightRegFile":
                    datatype_mapping["keep"] = ["Weights"]
                    datatype_mapping["bypass"] = ["Inputs", "Outputs"]
                elif level_name == "InputRegFile":
                    datatype_mapping["keep"] = ["Inputs"]
                    datatype_mapping["bypass"] = ["Weights", "Outputs"]
                elif level_name == "DummyBuffer":
                    # Dummy层bypass所有(pass-through)
                    datatype_mapping["bypass"] = ["Inputs", "Weights", "Outputs"]
                elif level_name == "GlobalBuffer":
                    # Global层保留Inputs和Outputs, bypass Weights
                    datatype_mapping["keep"] = ["Inputs", "Outputs"]
                    datatype_mapping["bypass"] = ["Weights"]
                elif level_name == "DRAM":
                    # DRAM保留所有数据
                    datatype_mapping["keep"] = ["Inputs", "Outputs", "Weights"]
            else:
                # 使用策略中指定的bypass
                datatype_mapping["bypass"] = bypass_list

            mapping["mapping"].append(datatype_mapping)

            # 3. Spatial mapping (如果有空间并行)
            spatial_tiles = level_strategy["spatial_tiles"]
            if any(v > 1 for v in spatial_tiles.values()):
                spatial_factors = " ".join([
                    f"{dim}={size}"
                    for dim, size in spatial_tiles.items() if size > 1
                ])
                spatial_mapping = {
                    "target": level_name,
                    "type": "spatial",
                    "factors": spatial_factors,
                    "permutation": perm_str  # 使用相同的permutation
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

    # 配置文件路径 (使用绝对路径，因为OpenEvolve会复制程序到临时目录)
    # 项目根目录固定为 /root/evolve_1108/cc_1108
    project_root = "/root/evolve_1108/cc_1108"
    config_dir = os.path.join(project_root, "config", "timeloop")
    arch_file = os.path.join(config_dir, "eyeriss.yaml")
    problem_file = os.path.join(config_dir, "problem.yaml")
    mapspace_file = os.path.join(config_dir, "mapspace.yaml")

    # 创建映射生成器
    generator = SoterMappingGenerator(arch_file, problem_file, mapspace_file)

    # 生成映射策略（EVOLVE-BLOCK会被OpenEvolve优化）
    strategy = generator.generate_mapping_strategy()

    # 转换为Timeloop格式
    timeloop_mapping = generator.convert_to_timeloop_mapping(strategy)

    # 保存结果到outputs/mappings/
    output_dir = os.path.join(project_root, "outputs", "mappings")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "generated_mapping.yaml")
    generator.save_mapping_to_file(timeloop_mapping, output_path)

    print(f"✅ Mapping generated successfully: {output_path}")
    print(f"📊 Strategy version: {strategy['meta']['version']}")

    return strategy


if __name__ == "__main__":
    result = main()
