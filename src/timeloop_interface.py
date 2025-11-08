"""
Timeloop Interface Layer
========================

固定的基础设施代码（不被LLM演化）

功能：
- 加载Timeloop配置（架构、问题）
- 解析硬件参数（buffer大小、空间约束）
- 验证算法决策（C_t, C_p, dimension budgets）
- 转换决策为Timeloop mapping YAML格式
- 执行Timeloop仿真并解析结果
"""

import os
import yaml
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple, Any


class TimeloopInterface:
    """Timeloop接口层 - 封装所有Timeloop交互逻辑"""

    def __init__(self, config_dir: str):
        """
        初始化Timeloop接口

        Args:
            config_dir: Timeloop配置文件目录路径
        """
        self.config_dir = Path(config_dir)

        # 加载配置文件
        self.arch_config = self._load_yaml(self.config_dir / "eyeriss.yaml")
        self.problem_config = self._load_yaml(self.config_dir / "problem.yaml")
        self.mapspace_config = self._load_yaml(self.config_dir / "mapspace.yaml")

        # 解析硬件参数
        self.buffer_levels = self._parse_buffer_hierarchy()
        self.buffer_sizes = self._parse_buffer_sizes()
        self.spatial_constraints = self._parse_spatial_constraints()
        self.problem_dims = self._parse_problem_dimensions()

        # 输出目录
        self.output_dir = Path("/root/evolve_1108/cc_1108/outputs/mappings")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _load_yaml(self, filepath: Path) -> Dict:
        """加载YAML配置文件"""
        with open(filepath, 'r') as f:
            return yaml.safe_load(f)

    def _parse_buffer_hierarchy(self) -> List[str]:
        """解析缓存层级（从内到外）"""
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
        # 计算公式: depth * width * word-bits / 8 (转换为字节)
        return {
            "InputRegFile": 3 * 64 * 16 // 8,           # 384 bytes
            "WeightRegFile": 48 * 64 * 16 // 8,         # 6144 bytes
            "PsumRegFile": 4 * 64 * 16 // 8,            # 512 bytes
            "DummyBuffer": 0,                            # pass-through
            "GlobalBuffer": 32768 * 64 * 16 // 8,       # 4MB
            "DRAM": 1024 * 1024 * 1024                   # 1GB (unlimited)
        }

    def _parse_spatial_constraints(self) -> Dict[str, int]:
        """解析空间并行约束（C_p约束）"""
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

    def validate_decisions(self, decisions: Dict) -> Tuple[bool, List[Dict]]:
        """
        验证算法决策是否满足所有硬件约束

        Args:
            decisions: algorithm.py生成的映射决策

        Returns:
            (is_valid, violations): 是否有效，约束违反列表
        """
        violations = []

        # 检查C_t约束（buffer容量）
        violations.extend(self._check_buffer_capacity(decisions))

        # 检查C_p约束（空间并行）
        violations.extend(self._check_spatial_constraints(decisions))

        # 检查维度预算守恒
        violations.extend(self._check_dimension_budgets(decisions))

        return (len(violations) == 0, violations)

    def _check_buffer_capacity(self, decisions: Dict) -> List[Dict]:
        """检查C_t约束：tile size ≤ buffer capacity"""
        violations = []

        for level in decisions["levels"]:
            level_name = level["level_name"]
            tiles = level["temporal_tiles"]

            buffer_capacity = self.buffer_sizes.get(level_name, float('inf'))

            # 跳过DummyBuffer (pass-through, capacity=0)
            if buffer_capacity == 0:
                continue

            # 计算tile size (简化: 假设每个元素16 bits = 2 bytes)
            # input_tile = N * P * Q * C
            # weight_tile = K * R * S * C
            # output_tile = P * Q * K * N
            input_size = tiles['N'] * tiles['P'] * tiles['Q'] * tiles['C'] * 2
            weight_size = tiles['K'] * tiles['R'] * tiles['S'] * tiles['C'] * 2
            output_size = tiles['P'] * tiles['Q'] * tiles['K'] * tiles['N'] * 2
            total_size = input_size + weight_size + output_size

            if total_size > buffer_capacity:
                violations.append({
                    "type": "buffer_capacity_exceeded",
                    "level": level_name,
                    "required": total_size,
                    "available": buffer_capacity,
                    "overflow_ratio": total_size / buffer_capacity,
                    "message": f"Buffer {level_name}: required {total_size} bytes > available {buffer_capacity} bytes"
                })

        return violations

    def _check_spatial_constraints(self, decisions: Dict) -> List[Dict]:
        """检查C_p约束：spatial product ≤ PE array size"""
        violations = []

        # 映射level_index到spatial constraint key
        spatial_map = {
            0: "l0", 1: "l0", 2: "l0",  # PE RegFiles
            3: "l1",  # DummyBuffer
            4: "l2",  # GlobalBuffer
            5: "l3"   # DRAM
        }

        for level in decisions["levels"]:
            level_idx = level["level_index"]
            spatial_tiles = level["spatial_tiles"]

            # 计算spatial product
            spatial_product = 1
            for dim, size in spatial_tiles.items():
                spatial_product *= size

            # 获取constraint
            constraint_key = spatial_map.get(level_idx, "l0")
            max_spatial = self.spatial_constraints.get(constraint_key, 1)

            if spatial_product > max_spatial:
                violations.append({
                    "type": "spatial_constraint_exceeded",
                    "level": constraint_key,
                    "level_index": level_idx,
                    "required": spatial_product,
                    "available": max_spatial,
                    "overflow_ratio": spatial_product / max_spatial,
                    "message": f"Spatial constraint {max_spatial} < required {spatial_product}"
                })

        return violations

    def _check_dimension_budgets(self, decisions: Dict) -> List[Dict]:
        """检查维度预算守恒：Π(temporal) × Π(spatial) = original dimension"""
        violations = []

        # 对每个维度，计算所有层级的tile乘积
        for dim in self.problem_dims:
            temporal_product = 1
            spatial_product = 1

            for level in decisions["levels"]:
                temporal_product *= level["temporal_tiles"].get(dim, 1)
                spatial_product *= level["spatial_tiles"].get(dim, 1)

            total_product = temporal_product * spatial_product
            expected = self.problem_dims[dim]

            if total_product != expected:
                violations.append({
                    "type": "dimension_budget_mismatch",
                    "dimension": dim,
                    "expected": expected,
                    "actual": total_product,
                    "message": f"Dimension {dim}: expected {expected}, got {total_product}"
                })

        return violations

    def convert_to_mapping(self, decisions: Dict) -> str:
        """
        将算法决策转换为Timeloop mapping YAML格式

        Args:
            decisions: algorithm.py生成的映射决策

        Returns:
            mapping_file_path: 生成的mapping文件路径
        """
        mapping = {"mapping": []}

        for level in decisions["levels"]:
            level_name = level["level_name"]

            # 1. Temporal mapping
            factors_str = " ".join([
                f"{dim}={size}"
                for dim, size in level["temporal_tiles"].items()
            ])
            perm_str = "".join(level["dimension_order"])

            temporal_mapping = {
                "target": level_name,
                "type": "temporal",
                "factors": factors_str,
                "permutation": perm_str
            }
            mapping["mapping"].append(temporal_mapping)

            # 2. Datatype bypass mapping
            datatype_mapping = {
                "target": level_name,
                "type": "datatype"
            }

            bypass_list = level.get("bypass", [])
            if bypass_list:
                datatype_mapping["bypass"] = bypass_list
            else:
                # 默认策略
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
                    datatype_mapping["bypass"] = ["Inputs", "Weights", "Outputs"]
                elif level_name == "GlobalBuffer":
                    datatype_mapping["keep"] = ["Inputs", "Outputs"]
                    datatype_mapping["bypass"] = ["Weights"]
                elif level_name == "DRAM":
                    datatype_mapping["keep"] = ["Inputs", "Outputs", "Weights"]

            mapping["mapping"].append(datatype_mapping)

            # 3. Spatial mapping (if有)
            spatial_tiles = level["spatial_tiles"]
            if any(v > 1 for v in spatial_tiles.values()):
                spatial_factors = " ".join([
                    f"{dim}={size}"
                    for dim, size in spatial_tiles.items() if size > 1
                ])
                spatial_mapping = {
                    "target": level_name,
                    "type": "spatial",
                    "factors": spatial_factors,
                    "permutation": perm_str
                }
                mapping["mapping"].append(spatial_mapping)

        # 保存YAML文件
        output_file = self.output_dir / "generated_mapping.yaml"
        with open(output_file, 'w') as f:
            yaml.dump(mapping, f, default_flow_style=False)

        return str(output_file)

    def run_timeloop(self, mapping_file: str) -> Dict[str, Any]:
        """
        运行Timeloop仿真

        Args:
            mapping_file: mapping文件路径

        Returns:
            stats: 仿真统计结果 {latency, energy, edp, ...}
        """
        # 构造Timeloop命令
        cmd = [
            "timeloop-model",
            str(self.config_dir / "eyeriss.yaml"),
            str(self.config_dir / "problem.yaml"),
            mapping_file
        ]

        # 执行仿真
        try:
            result = subprocess.run(
                cmd,
                cwd=self.output_dir,
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": result.stderr,
                    "latency": 0,
                    "energy": 0,
                    "edp": float('inf')
                }

            # 解析stats文件
            stats = self._parse_timeloop_stats()
            stats["success"] = True
            return stats

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Timeloop execution timeout",
                "latency": 0,
                "energy": 0,
                "edp": float('inf')
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "latency": 0,
                "energy": 0,
                "edp": float('inf')
            }

    def _parse_timeloop_stats(self) -> Dict[str, float]:
        """解析Timeloop生成的stats文件"""
        stats_file = self.output_dir / "timeloop-model.stats.txt"

        if not stats_file.exists():
            return {
                "latency": 0,
                "energy": 0,
                "edp": float('inf')
            }

        stats = {}
        with open(stats_file, 'r') as f:
            content = f.read()

            # 提取关键指标 (简化版本，实际需要更健壮的解析)
            import re

            # Latency (cycles)
            latency_match = re.search(r'Cycles:\s+(\d+)', content)
            if latency_match:
                stats['latency'] = int(latency_match.group(1))
            else:
                stats['latency'] = 0

            # Energy (uJ)
            energy_match = re.search(r'Energy \(total\)\s+:\s+([\d.]+)\s+uJ', content)
            if energy_match:
                stats['energy'] = float(energy_match.group(1))
            else:
                stats['energy'] = 0

            # 计算EDP
            stats['edp'] = stats['latency'] * stats['energy']

        return stats


# ============================================
# 测试接口
# ============================================

if __name__ == "__main__":
    # 测试Timeloop接口
    interface = TimeloopInterface("/root/evolve_1108/cc_1108/config/timeloop")

    print("✅ Timeloop Interface Initialized")
    print(f"   Buffer levels: {interface.buffer_levels}")
    print(f"   Problem dimensions: {interface.problem_dims}")
    print(f"   Spatial constraints: {interface.spatial_constraints}")

    # 测试决策验证 (使用baseline决策)
    test_decisions = {
        "meta": {"version": "test"},
        "levels": [
            {
                "level_name": "PsumRegFile",
                "level_index": 0,
                "temporal_tiles": {'N': 1, 'K': 1, 'C': 1, 'P': 1, 'Q': 1, 'R': 1, 'S': 3},
                "spatial_tiles": {'N': 1, 'K': 1, 'C': 1, 'P': 1, 'Q': 1, 'R': 1, 'S': 1},
                "dimension_order": ["R", "S", "P", "Q", "C", "K", "N"],
                "bypass": []
            },
            # ... (其他层级省略)
        ]
    }

    is_valid, violations = interface.validate_decisions(test_decisions)
    print(f"\n📋 Validation result: {'✅ Valid' if is_valid else '❌ Invalid'}")
    if violations:
        print(f"   Violations: {len(violations)}")
        for v in violations[:3]:  # 只显示前3个
            print(f"   - {v['type']}: {v['message']}")
