"""
Eyeriss Mapping Algorithm
==========================

这是LLM演化的唯一文件！

功能：为Eyeriss加速器生成DNN映射决策
输入：问题维度(N, K, C, P, Q, R, S)
输出：映射决策(temporal_tiles, spatial_tiles, dimension_order, bypass)

约束：
- C_t (Buffer Capacity): tile size ≤ buffer capacity
- C_p (Spatial Parallelism): spatial product ≤ PE array size
- Dimension Budget: Π(temporal) × Π(spatial) = original dimension
"""

from typing import Dict, List


# ============================================
# EVOLVE-BLOCK-START: LLM优化这些决策函数
# ============================================

def decide_temporal_tiles(level_idx: int, level_name: str,
                          problem_dims: Dict[str, int],
                          buffer_sizes: Dict[str, int]) -> Dict[str, int]:
    """
    决策时间分块大小（X_t参数）

    **优化方向**：
    - 更大的tile提高数据重用（但需满足C_t约束）
    - 应利用buffer大小最大化重用
    - 不同层级应有不同的tile策略

    Args:
        level_idx: 层级索引 (0=PsumRegFile, 4=GlobalBuffer, 5=DRAM)
        level_name: 层级名称
        problem_dims: {N:1, K:32, C:3, P:224, Q:224, R:3, S:3}
        buffer_sizes: {PsumRegFile: 512, GlobalBuffer: 4MB, ...}

    Returns:
        temporal_tiles: {N:1, K:4, C:1, P:7, Q:8, R:1, S:1}

    Constraints:
        - Total tile size ≤ buffer_sizes[level_name]
        - Π(all levels' tiles) = original dimension
    """
    # BASELINE策略：保守的均匀分块

    if level_name == "PsumRegFile":
        # PE level - 512 bytes capacity
        return {'N': 1, 'K': 1, 'C': 1, 'P': 1, 'Q': 1, 'R': 1, 'S': 3}

    elif level_name == "WeightRegFile":
        # PE level - 6KB capacity
        return {'N': 1, 'K': 1, 'C': 1, 'P': 1, 'Q': 1, 'R': 3, 'S': 1}

    elif level_name == "InputRegFile":
        # PE level - 384 bytes capacity
        return {'N': 1, 'K': 1, 'C': 1, 'P': 1, 'Q': 1, 'R': 1, 'S': 1}

    elif level_name == "DummyBuffer":
        # Pass-through layer - 0 capacity
        return {'N': 1, 'K': 1, 'C': 1, 'P': 1, 'Q': 1, 'R': 1, 'S': 1}

    elif level_name == "GlobalBuffer":
        # Global SRAM - 4MB capacity
        # 保留中等tile size用于weight和activation重用
        return {'N': 1, 'K': 4, 'C': 1, 'P': 7, 'Q': 8, 'R': 1, 'S': 1}

    elif level_name == "DRAM":
        # Main memory - 计算剩余dimension
        # 确保Π(all levels) = original dimension
        N = problem_dims['N']
        K = problem_dims['K'] // 4  # GlobalBuffer已用K=4
        C = problem_dims['C']
        P = problem_dims['P'] // 7  # GlobalBuffer已用P=7
        Q = problem_dims['Q'] // 8  # GlobalBuffer已用Q=8
        R = problem_dims['R'] // 3  # WeightRegFile已用R=3
        S = problem_dims['S'] // 3  # PsumRegFile已用S=3

        return {'N': N, 'K': K, 'C': C, 'P': P, 'Q': Q, 'R': R, 'S': S}

    else:
        # Default: 全1
        return {dim: 1 for dim in problem_dims}


def decide_spatial_tiles(level_idx: int, level_name: str,
                        problem_dims: Dict[str, int],
                        spatial_constraints: Dict[str, int]) -> Dict[str, int]:
    """
    决策空间并行分块（X_p参数）

    **优化方向**：
    - 空间并行减少延迟（提高吞吐）
    - Eyeriss支持P/Q维度的空间展开
    - 需满足C_p约束（PE数量限制）

    Args:
        level_idx: 层级索引
        level_name: 层级名称
        problem_dims: 问题维度
        spatial_constraints: {l0:1, l1:14, l2:12, l3:1}

    Returns:
        spatial_tiles: {N:1, K:1, C:1, P:2, Q:7, R:1, S:1}

    Constraints:
        - Π(spatial_tiles) ≤ spatial_constraints[level]
        - Π(temporal × spatial) = original dimension
    """
    # BASELINE策略：无空间并行（最保守）
    # 优化空间：可在DummyBuffer(14 PEs)和GlobalBuffer(12 PEs)使用

    return {dim: 1 for dim in problem_dims}


def decide_dimension_order(level_idx: int, level_name: str) -> List[str]:
    """
    决策维度遍历顺序（X_d参数）

    **优化方向**：
    - 影响数据重用模式（inner loop重用更多）
    - Eyeriss row-stationary: R/S应在内层
    - 不同层级应有不同顺序以最大化重用

    Args:
        level_idx: 层级索引
        level_name: 层级名称

    Returns:
        dimension_order: ["R", "S", "C", "P", "Q", "K", "N"]

    Best Practices:
        - PE level: R/S内层（最小数据移动）
        - Global level: C内层（weight重用）
        - DRAM level: N外层（batch并行）
    """
    # BASELINE策略：固定顺序

    baseline_orders = {
        0: ["R", "S", "P", "Q", "C", "K", "N"],  # PsumRegFile
        1: ["R", "S", "P", "Q", "C", "K", "N"],  # WeightRegFile
        2: ["R", "S", "P", "Q", "C", "K", "N"],  # InputRegFile
        3: ["P", "Q", "R", "S", "C", "K", "N"],  # DummyBuffer
        4: ["C", "K", "P", "Q", "R", "S", "N"],  # GlobalBuffer
        5: ["N", "K", "C", "P", "Q", "R", "S"]   # DRAM
    }

    return baseline_orders.get(level_idx, ["N", "K", "C", "P", "Q", "R", "S"])


def decide_bypass_strategy(level_idx: int, level_name: str) -> List[str]:
    """
    决策Bypass策略（哪些数据跳过此层）

    **优化方向**：
    - Bypass减少无效数据搬运
    - 权衡数据重用 vs 带宽压力
    - PE level RegFiles应各自保留专用数据类型

    Args:
        level_idx: 层级索引
        level_name: 层级名称

    Returns:
        bypass_list: ["Weights"] 或 [] (空=不bypass)

    Datatype Options:
        - "Inputs": activation数据
        - "Weights": 权重数据
        - "Outputs": partial sums
    """
    # BASELINE策略：不bypass（最保守，全部keep）
    # 优化空间：可bypass GlobalBuffer的weights以节省存储

    return []

# EVOLVE-BLOCK-END
# ============================================


# ============================================
# 主接口（固定，不演化）
# ============================================

def generate_mapping_decisions(problem_dims: Dict[str, int],
                                buffer_levels: List[str],
                                buffer_sizes: Dict[str, int],
                                spatial_constraints: Dict[str, int]) -> Dict:
    """
    生成完整的映射决策（被evaluator调用）

    这个函数是固定的接口，LLM不应修改！
    LLM只应优化上面的decide_*函数。

    Args:
        problem_dims: 问题维度 {N:1, K:32, C:3, P:224, Q:224, R:3, S:3}
        buffer_levels: buffer层级列表 ["PsumRegFile", ..., "DRAM"]
        buffer_sizes: 各层容量 {PsumRegFile: 512, ...}
        spatial_constraints: 空间约束 {l0:1, l1:14, l2:12, l3:1}

    Returns:
        mapping_decisions: {
            "meta": {...},
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
    decisions = {
        "meta": {
            "version": "algorithm_v1",
            "description": "Separated algorithm - Baseline strategy",
            "problem_dimensions": problem_dims
        },
        "levels": []
    }

    for level_idx, level_name in enumerate(buffer_levels):
        level_decision = {
            "level_name": level_name,
            "level_index": level_idx,
            "temporal_tiles": decide_temporal_tiles(
                level_idx, level_name, problem_dims, buffer_sizes
            ),
            "spatial_tiles": decide_spatial_tiles(
                level_idx, level_name, problem_dims, spatial_constraints
            ),
            "dimension_order": decide_dimension_order(level_idx, level_name),
            "bypass": decide_bypass_strategy(level_idx, level_name)
        }
        decisions["levels"].append(level_decision)

    return decisions


# ============================================
# 测试接口
# ============================================

if __name__ == "__main__":
    # 测试算法 - 使用实际的ResNet50 first layer dimensions
    test_problem_dims = {
        'N': 1, 'K': 32, 'C': 3,
        'P': 224, 'Q': 224, 'R': 3, 'S': 3
    }

    test_buffer_levels = [
        "PsumRegFile", "WeightRegFile", "InputRegFile",
        "DummyBuffer", "GlobalBuffer", "DRAM"
    ]

    test_buffer_sizes = {
        "PsumRegFile": 512,
        "WeightRegFile": 6144,
        "InputRegFile": 384,
        "DummyBuffer": 0,
        "GlobalBuffer": 4 * 1024 * 1024,
        "DRAM": 1024 * 1024 * 1024
    }

    test_spatial_constraints = {
        "l0": 1, "l1": 14, "l2": 12, "l3": 1
    }

    decisions = generate_mapping_decisions(
        test_problem_dims,
        test_buffer_levels,
        test_buffer_sizes,
        test_spatial_constraints
    )

    print("✅ Algorithm test passed!")
    print(f"Generated decisions for {len(decisions['levels'])} levels")
    print(f"GlobalBuffer temporal tiles: {decisions['levels'][4]['temporal_tiles']}")
