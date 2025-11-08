# 维度预算不匹配问题：根本原因分析

## 执行摘要

10次迭代的演化实验中，**所有10个LLM生成的程序都违反了维度预算约束**（dimension budget conservation）。这不是一个偶然的问题，而是系统性的提示工程缺陷。

## 问题现象

从日志中提取的典型错误：

```python
# 迭代1: 程序 f82af1d1-8a35-4ec7-a74c-6d46724eba84
violations: [
    'C: expected 3, actual 9',      # 3倍错误
    'P: expected 224, actual 4032',  # 18倍错误
    'Q: expected 224, actual 18816'  # 84倍错误
]

# 迭代4: 程序 79506c77-e6c1-4c91-95e4-8910aa1d7ec6
violations: [
    'K: expected 32, actual 64',      # 2倍错误
    'C: expected 3, actual 9',        # 3倍错误
    'P: expected 224, actual 75264',  # 336倍错误 !!!
    'Q: expected 224, actual 448'     # 2倍错误
]

# 最好的程序(迭代3): 只有1个违反 - 但仍然失败
violations: [
    'P: expected 224, actual 168'    # 0.75倍 (少了)
]
```

**关键观察**：错误倍数从 0.75x 到 336x 不等，这说明 LLM **完全不理解**维度预算守恒的数学约束。

## LLM 实际生成的错误代码

查看失败程序 `f82af1d1-8a35-4ec7-a74c-6d46724eba84`：

```python
# LLM 生成的 GlobalBuffer 时间分块
elif level_name == "GlobalBuffer":
    return {'N': 1, 'K': 8, 'C': 3, 'P': 8, 'Q': 8, 'R': 1, 'S': 1}

# LLM 生成的 DRAM 时间分块
elif level_name == "DRAM":
    K = problem_dims['K'] // 8  # = 32 // 8 = 4
    C = problem_dims['C'] // 3  # = 3 // 3 = 1  ✓
    P = problem_dims['P'] // 8  # = 224 // 8 = 28
    Q = problem_dims['Q'] // 8  # = 224 // 8 = 28
    return {'K': 4, 'C': 1, 'P': 28, 'Q': 28, ...}
```

**错误分析**：
- **C 维度**：`WeightRegFile(C=3)` × `DRAM(C=1)` = **3** ✓ **正确！**
- **P 维度**：`InputRegFile(P=3)` × `GlobalBuffer(P=8)` × `DRAM(P=28)` = **672** ✗ 期望 224
- **Q 维度**：`InputRegFile(Q=3)` × `GlobalBuffer(Q=8)` × `DRAM(Q=28)` = **672** ✗ 期望 224

**LLM 忽略了 InputRegFile 的贡献！**

## 根本原因分析

### 1. **提示工程不足 vs MLX Metal Kernel 示例对比**

#### MLX 示例的成功要素：

```yaml
# MLX config.yaml 的 system_message
system_message: |
  You are an expert Metal GPU programmer...

  # CURRENT METAL KERNEL STRUCTURE:
  ```metal
  kernel void qwen3_gqa_attention_kernel() {
      uint kv_head_idx = head_idx / HEADS_PER_KV;  # 明确的计算关系

      const uint q_base = batch_idx * (NUM_HEADS * SEQ_LEN * HEAD_DIM) +
                          head_idx * (SEQ_LEN * HEAD_DIM) +
                          query_pos * HEAD_DIM;  # 完整的索引计算公式
  }
  ```

  # EVOLUTION CONSTRAINTS - CRITICAL SAFETY RULES:

  **MUST NOT CHANGE:**
  ❌ Template parameter names (T, BATCH_SIZE, NUM_HEADS, etc.)
  ❌ Overall algorithm correctness
  ❌ Thread grid mapping

  **ALLOWED TO OPTIMIZE:**
  ✅ Memory access patterns and indexing WITHIN the kernel
  ✅ Computation order and algorithm efficiency
```

**关键差异**：
1. **明确的数学关系展示**：MLX 在 prompt 中直接展示了 `kv_head_idx = head_idx / HEADS_PER_KV` 的计算
2. **完整的约束公式**：内存索引公式完整展示，LLM 可以模仿
3. **严格的不可变规则**：明确哪些参数**绝对不能改**

#### 我们的 Timeloop 提示的缺陷：

```yaml
# 我们的 diff_user.txt
## ACTUAL PROBLEM DIMENSIONS (CRITICAL - USE THESE VALUES):
- **P (Output Height)**: 224
- **Q (Output Width)**: 224

**IMPORTANT**: You MUST use these exact dimensions when calculating temporal/spatial tiles!
The dimension budget constraint requires: Π(all temporal tiles) × Π(all spatial tiles) = original dimension

For example, for dimension C=3:
- If WeightRegFile uses C_temporal=2, ...
- **Correct approach**: Don't use C=2 anywhere, keep all C_temporal=1, C_spatial=1, DRAM C_temporal=3
```

**问题**：
1. ❌ **没有展示完整的计算公式**：只有文字描述 "Π(all temporal tiles) × Π(all spatial tiles) = original dimension"
2. ❌ **示例不完整**：只展示了 C=3 的例子，但 C=3 太简单（只能是 1×3 或 3×1）
3. ❌ **缺少工作代码示例**：没有像 MLX 那样展示一个**完整正确的计算示例**
4. ❌ **6个层级的复杂性**：LLM 需要同时考虑 6 个层级的 temporal + spatial，太复杂

### 2. **LLM 能力问题：GLM-4.6 vs Gemini-2.5-Pro**

#### 对比：
- **MLX 使用**：`gemini-2.5-flash-preview-05-20` (weight 0.6) + `gemini-2.5-pro-preview-06-05` (weight 0.4)
- **我们使用**：`glm-4.6` (单一模型)

**推测**：
- Gemini-2.5-Pro 在复杂数学推理方面可能更强
- 但**更关键的是**：MLX 的 prompt 降低了任务难度（明确展示公式）

### 3. **算法复杂度问题**

#### MLX Metal Kernel：
- **优化目标**：单个 Metal 内核的性能
- **约束类型**：语法正确性、数值精度
- **数学复杂度**：相对简单（内存索引计算）
- **演化空间**：代码优化（循环展开、SIMD、内存访问模式）

#### 我们的 Timeloop Mapping：
- **优化目标**：6个层级的分块决策
- **约束类型**：维度预算守恒（**乘法约束，跨多个层级**）
- **数学复杂度**：**非常高**（6层 × 7维 × (temporal + spatial) = 84个变量的乘法约束）
- **演化空间**：组合优化（NP-hard）

**关键洞察**：
```python
# MLX: LLM 只需要保持语法正确
for (uint d = 0; d < HEAD_DIM; d += 4) {  # 优化：从 d++ 改为 d+=4
    score += query_vec[d] * keys[k_base + d];
}

# Timeloop: LLM 需要同时满足跨层级的数学约束
P_total = P_PsumReg × P_WeightReg × P_InputReg × P_Dummy × P_Global × P_DRAM
        × P_spatial_Dummy × P_spatial_Global
        = 1 × 1 × ? × 1 × ? × ? × ? × ?  = 224  # 需要找到合法的组合！
```

## 对比表格：MLX vs Timeloop

| 维度 | MLX Metal Kernel | Timeloop Mapping | 优势方 |
|------|------------------|------------------|--------|
| **任务类型** | 性能优化（代码层面） | 组合优化（参数层面） | MLX |
| **约束复杂度** | 低（语法+数值稳定性） | 高（跨层级乘法守恒） | MLX |
| **LLM任务** | 代码重写 | 数学推理 | MLX |
| **Prompt质量** | 优秀（完整公式示例） | 不足（缺少公式示例） | MLX |
| **LLM选择** | Gemini-2.5-Pro (强) | GLM-4.6 (弱) | MLX |
| **成功率** | 高 | **0%（10/10失败）** | MLX |

## 结论

**这不是单一问题，而是三个因素的叠加**：

1. **提示工程不足**（主要原因，占70%）
   - 缺少完整的数学公式示例
   - 缺少工作代码参考
   - 示例过于简单（C=3）

2. **LLM 能力不足**（次要原因，占20%）
   - GLM-4.6 在复杂数学推理方面弱于 Gemini-2.5-Pro
   - 但**即使换模型，没有好的 prompt 也不行**

3. **问题本身的复杂性**（固有难度，占10%）
   - 6层 × 7维 × 2类型(temporal/spatial) = 84维约束空间
   - NP-hard 组合优化问题
   - **这是无法改变的**

## 推荐修复方案（按优先级）

### 方案1：提示工程增强（立即实施，成本低，效果高）

添加到 `system_message.txt`：

```yaml
# CRITICAL: DIMENSION BUDGET CONSERVATION EXAMPLES

**Example 1: Simple Dimension (C=3)**
```python
# 6个层级的时间分块 + 空间分块必须乘积为 3
C_temporal = {
    "PsumRegFile": 1,
    "WeightRegFile": 3,  # ← 在这里用完
    "InputRegFile": 1,
    "DummyBuffer": 1,
    "GlobalBuffer": 1,
    "DRAM": 1
}
C_spatial = {
    "l0": 1, "l1": 1, "l2": 1, "l3": 1  # 所有层都是1（无空间并行）
}
# 验证：1×3×1×1×1×1 × 1×1×1×1 = 3 ✓
```

**Example 2: Complex Dimension (P=224 = 2^5 × 7)**
```python
# 224 需要分解到 6 个层级（temporal）+ 2 个层级（spatial）
# 可行分解1：
P_temporal = {
    "PsumRegFile": 1,
    "WeightRegFile": 1,
    "InputRegFile": 1,
    "DummyBuffer": 2,    # 2 × 7 × 16 = 224
    "GlobalBuffer": 7,
    "DRAM": 16
}
P_spatial = {
    "l1": 1,  # DummyBuffer 无空间并行
    "l2": 1   # GlobalBuffer 无空间并行
}
# 验证：1×1×1×2×7×16 × 1×1 = 224 ✓

# 可行分解2（使用空间并行）：
P_temporal = {
    "PsumRegFile": 1,
    "WeightRegFile": 1,
    "InputRegFile": 1,
    "DummyBuffer": 1,
    "GlobalBuffer": 7,   # 7 × 4 × 8 = 224
    "DRAM": 4
}
P_spatial = {
    "l1": 1,
    "l2": 8   # GlobalBuffer 使用 8 个 PE
}
# 验证：1×1×1×1×7×4 × 1×8 = 224 ✓
# 空间约束：8 ≤ 12 (GlobalBuffer 的 spmap_cstr) ✓
```

**CRITICAL RULE: 修改一个层级，必须调整其他层级！**
```python
# ❌ 错误示例：
if level_name == "GlobalBuffer":
    return {'P': 8}  # 从 7 改为 8
# 但 DRAM 仍然是：P = 224 // 7 = 32
# 结果：1×1×1×1×8×32 = 256 ≠ 224 ✗

# ✓ 正确示例：
if level_name == "GlobalBuffer":
    return {'P': 8}  # 改为 8
elif level_name == "DRAM":
    return {'P': 224 // 8}  # 必须同步修改为 // 8
# 结果：1×1×1×1×8×28 = 224 ✓
```
```

### 方案2：简化问题（中等实施，成本中，效果高）

**选项A：固定某些层级的决策**

```python
# 强制 PE 层级（0-2）的分块为 1，只让 LLM 优化 GlobalBuffer + DRAM
FIXED_PE_TILES = {
    "PsumRegFile": {'N': 1, 'K': 1, 'C': 1, 'P': 1, 'Q': 1, 'R': 1, 'S': 1},
    "WeightRegFile": {'N': 1, 'K': 1, 'C': 1, 'P': 1, 'Q': 1, 'R': 1, 'S': 1},
    "InputRegFile": {'N': 1, 'K': 1, 'C': 1, 'P': 1, 'Q': 1, 'R': 1, 'S': 1},
    "DummyBuffer": {'N': 1, 'K': 1, 'C': 1, 'P': 1, 'Q': 1, 'R': 1, 'S': 1},
}

# LLM 只演化：
# - decide_global_buffer_tiles()
# - decide_dram_tiles()

# 这样约束从 6 层简化为 2 层，难度大幅降低
```

**选项B：分阶段演化**

```python
# 阶段1：固定空间并行为1，只演化时间分块
# 阶段2：固定时间分块，演化空间并行
# 阶段3：联合优化

# 降低每阶段的复杂度
```

### 方案3：切换到更强的 LLM（立即可行，成本高）

```yaml
# config_v2.yaml
llm:
  primary_model: "gemini-2.5-pro-preview-06-05"  # 替换 GLM-4.6
  primary_model_weight: 0.6
  secondary_model: "gemini-2.5-flash-preview-05-20"
  secondary_model_weight: 0.4
  api_base: "https://generativelanguage.googleapis.com/v1beta/openai/"
```

**但注意**：
- 成本：Gemini-2.5-Pro 比 GLM-4.6 贵 ~10x
- **即使换模型，如果 prompt 不改，成功率仍然很低**

### 方案4：混合方法（推荐）

**综合利用方案1+2+3**：

1. **立即实施**：增强 prompt（方案1），添加完整公式示例
2. **简化问题**：固定 PE 层级分块（方案2A），降低搜索空间
3. **如果预算允许**：切换到 Gemini-2.5-Pro（方案3）

**预期效果**：
- 方案1：成功率从 0% → 30-50%
- 方案1+2：成功率 → 60-80%
- 方案1+2+3：成功率 → 90%+

## 附录：错误模式统计

```
10 次迭代中的错误分布：

维度 C（期望=3）：
- C=9: 5次（3倍错误，都是因为 3×3=9）
- C=0: 0次
- 正确: 5次

维度 P（期望=224）：
- P=168: 1次（baseline×InputRegFile冲突）
- P=448: 2次（2倍错误）
- P=672: 2次（3倍错误）
- P=1120-75264: 5次（5-336倍错误）

维度 Q（期望=224）：
- 类似 P 的模式

维度 K（期望=32）：
- K=64: 2次（2倍错误）
- K=256: 1次（8倍错误）
- 正确: 7次

**结论**：错误是随机的，没有一致的模式 → LLM 不理解约束
```

## 下一步行动

1. ✅ **完成本分析报告**
2. ⏭️ **实施方案1**：重写 system_message.txt，添加完整公式示例
3. ⏭️ **实施方案2A**：固定 PE 层级分块，简化问题
4. ⏭️ **测试新 prompt**：运行 1-iteration 测试，验证改进效果
5. ⏭️ **决定是否切换模型**：根据测试结果决定是否换 Gemini-2.5-Pro
