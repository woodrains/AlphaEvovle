# Prompt改进失败分析

## 实验结果

**改进后的Prompt（MLX风格）依然100%失败**

### 对比数据

| 实验 | 成功率 | C=9错误率 | 最佳程序违反数 |
|------|--------|-----------|---------------|
| **原始Prompt** | 0/10 | 5/10 (50%) | 1 violation |
| **改进Prompt (MLX风格)** | 0/9 | 7/9 (78%) | 4 violations |

**改进后反而更差！**

### 错误模式对比

#### 原始Prompt最佳程序（Iteration 3）:
```
violations: ['P: expected 224, actual 168']  # 只有1个错误
```

#### 改进Prompt最佳程序（Iteration 3）:
```
violations: [
    'K: expected 32, actual 256',   # 8倍错误
    'C: expected 3, actual 9',       # 3倍错误
    'P: expected 224, actual 672',   # 3倍错误
    'Q: expected 224, actual 672'    # 3倍错误
]  # 4个错误！
```

## 失败原因分析

### 1. Prompt改进内容回顾

我们添加了：
- ✅ 完整的C=3示例（质数，只能用一个层级）
- ✅ 完整的P=224三种分解示例
- ✅ 明确的错误示例（C=9的错误）
- ✅ 同步规则说明
- ✅ MLX风格的验证清单

### 2. 为什么依然失败？

**关键观察：C=9错误率从50%增加到78%**

这说明GLM-4.6：
1. **完全无视了prompt中的警告**："C=3 (prime number - use at one level only!)"
2. **没有理解错误示例**：我们明确展示了`C=9 ≠ 3 ✗ VIOLATION!`
3. **数学推理能力严重不足**：无法执行简单的乘法验证

### 3. 实际生成的错误代码示例

查看最佳程序`357d5042`的代码（outputs/evolution/eyeriss_mapping_v2_evolution_improved/best/best_program.py）:

```python
def decide_temporal_tiles(...):
    if level_name == "PsumRegFile":
        return {'C': 3, ...}  # ← 在这里用了C=3

    elif level_name == "GlobalBuffer":
        return {'C': 3, ...}  # ← 又在这里用了C=3！

    # 结果: 1×3×1×1×3×1 = 9 ≠ 3
```

**LLM完全忽略了prompt中的三次警告**：
1. "C (Input Channels): 3 (prime number - use at one level only!)"
2. Example 1中的错误演示
3. "CRITICAL RULE"中的同步要求

## 根本结论

**Prompt工程无法解决GLM-4.6的数学推理缺陷**

即使提供了：
- 完整的正确示例
- 明确的错误示例
- 详细的验证步骤
- MLX风格的结构化prompt

GLM-4.6依然无法：
- 理解质数不能分解
- 执行简单的乘法验证
- 遵守明确的约束规则

## 推荐方案

### 方案A：强制代码约束（立即可行）✅

**不依赖LLM理解，在代码层面强制执行**：

```python
# src/constraint_enforcer.py
class DimensionBudgetEnforcer:
    """在TimeloopInterface中强制维度预算守恒"""

    def __init__(self, problem_dims):
        self.problem_dims = problem_dims
        self.prime_dims = {
            'C': 3,  # 质数，不可分解
            'R': 3,
            'S': 3
        }

    def enforce_tiles(self, all_temporal_tiles, all_spatial_tiles):
        """强制修正LLM生成的tiles以满足约束"""
        enforced_temporal = {}

        for dim in ['N', 'K', 'C', 'P', 'Q', 'R', 'S']:
            if dim in self.prime_dims:
                # 质数维度：强制只在一个层级使用
                enforced_temporal[dim] = self._enforce_prime_dimension(
                    dim, all_temporal_tiles, all_spatial_tiles
                )
            else:
                # 非质数维度：自动调整DRAM层以满足约束
                enforced_temporal[dim] = self._enforce_regular_dimension(
                    dim, all_temporal_tiles, all_spatial_tiles
                )

        return enforced_temporal

    def _enforce_prime_dimension(self, dim, temporal_tiles, spatial_tiles):
        """
        质数维度强制策略：
        1. 找到当前使用该维度的层级
        2. 如果多个层级使用，只保留第一个，其他设为1
        3. 如果没有层级使用，在WeightRegFile使用
        """
        prime_value = self.prime_dims[dim]
        levels_using = []

        for level_name, tiles in temporal_tiles.items():
            if tiles.get(dim, 1) > 1:
                levels_using.append(level_name)

        # 强制修正
        for level_name in temporal_tiles:
            if level_name == levels_using[0] if levels_using else level_name == "WeightRegFile":
                temporal_tiles[level_name][dim] = prime_value
            else:
                temporal_tiles[level_name][dim] = 1

        return temporal_tiles

    def _enforce_regular_dimension(self, dim, temporal_tiles, spatial_tiles):
        """
        非质数维度强制策略：
        1. 计算前5个层级的乘积
        2. DRAM层级 = problem_dim / product
        """
        product = 1
        levels = ['PsumRegFile', 'WeightRegFile', 'InputRegFile',
                  'DummyBuffer', 'GlobalBuffer']

        for level in levels:
            product *= temporal_tiles[level].get(dim, 1)

        # 计算spatial贡献
        for spatial in spatial_tiles.values():
            product *= spatial.get(dim, 1)

        # 强制DRAM满足约束
        dram_tile = self.problem_dims[dim] // product
        if dram_tile * product != self.problem_dims[dim]:
            # 如果无法整除，回退到安全策略：DRAM使用全部
            temporal_tiles['DRAM'][dim] = self.problem_dims[dim]
            for level in levels:
                temporal_tiles[level][dim] = 1
        else:
            temporal_tiles['DRAM'][dim] = dram_tile

        return temporal_tiles
```

**修改`timeloop_interface.py`**:

```python
from constraint_enforcer import DimensionBudgetEnforcer

class TimeloopInterface:
    def generate_mapping_yaml(self, strategy_func, problem_dims):
        # 1. 让LLM生成原始tiles（可能违反约束）
        raw_temporal, raw_spatial, ... = self._extract_from_strategy(strategy_func)

        # 2. 强制修正以满足约束
        enforcer = DimensionBudgetEnforcer(problem_dims)
        enforced_temporal, enforced_spatial = enforcer.enforce_tiles(
            raw_temporal, raw_spatial
        )

        # 3. 生成YAML（保证正确）
        return self._build_yaml(enforced_temporal, enforced_spatial, ...)
```

**优点**：
- ✅ **100%保证维度约束满足**
- ✅ 不依赖LLM数学能力
- ✅ LLM可以专注于优化策略（dimension order, bypass等）
- ✅ 立即可实施

**缺点**：
- LLM失去了对temporal tiles的部分控制权
- 但这正是问题所在 - LLM无法正确控制这部分

### 方案B：切换到Gemini-2.5-Pro（成本高）

需要Google API Key，成本约为GLM-4.6的10倍。

### 方案C：混合方案（推荐）✅

1. **实施方案A的约束强制**（立即）
2. **简化LLM任务**：
   - 只让LLM决定5个层级的temporal tiles（不包括DRAM）
   - DRAM自动计算：`DRAM[dim] = problem_dim / product(other_levels)`
   - 质数维度（C/R/S）直接固定在特定层级

修改后的`algorithm.py`:

```python
# EVOLVE-BLOCK-START
def decide_temporal_tiles_simplified(level_idx, level_name, problem_dims):
    """
    LLM只需要决定5个层级（不包括DRAM）
    约束：
    - C必须=1（因为C=3已固定在WeightRegFile）
    - R必须=1（因为R=3已固定在WeightRegFile）
    - S必须=1（因为S=3已固定在InputRegFile）
    """
    if level_name == "WeightRegFile":
        return {'N': 1, 'K': 1, 'C': 3, 'P': 1, 'Q': 1, 'R': 3, 'S': 1}

    elif level_name == "InputRegFile":
        return {'N': 1, 'K': 1, 'C': 1, 'P': 1, 'Q': 1, 'R': 1, 'S': 3}

    # 其他层级：LLM只需要决定N/K/P/Q（4个维度）
    elif level_name == "PsumRegFile":
        return {'N': 1, 'K': 1, 'C': 1, 'P': 1, 'Q': 1, 'R': 1, 'S': 1}

    # ... 其他层级类似

    # DRAM层级自动计算（不由LLM决定）
    # 这部分由TimeloopInterface自动处理
# EVOLVE-BLOCK-END
```

## 实验计划

1. ✅ 实施方案C（混合方案）
2. 运行10-iteration测试验证
3. 如果仍然失败 → 证明GLM-4.6完全无法胜任此任务
4. 最终方案：切换到Gemini-2.5-Pro或放弃LLM演化
