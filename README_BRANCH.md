# Branch: eyeriss-optimization-success-v1

## 🎯 分支目的

这个分支展示了通过精心设计的 **Prompt Engineering** 修复 OpenEvolve + DeepSeek-R1 在 Eyeriss 硬件映射优化中的约束违反问题，并成功实现 **92% EDP 改进**的完整过程。

---

## ✅ 主要成果

### 性能改进
- **EDP**: 1.88e9 → 1.50e8 (**92.0% 改进**)
- **Latency**: 43,352,064 → 3,462,144 cycles (**92.0% 降低**)
- **Energy**: 43.35 uJ (保持不变)

### 约束违反率
- **修复前**: 100% 违反率 (所有程序都违反维度预算约束)
- **修复后**: 10% 违反率 (18/20 程序通过 Stage 1 验证)

### 关键发现
- **DRAM 访问减少**: 112 倍 (7168 → 64 blocks)
- **GlobalBuffer 利用率**: 8 倍提升 (224 → 1792 elements per tile)
- **空间并行度**: 激活 14 个 PE (2×7 spatial parallelism)

---

## 📁 关键文件

### 修复文档
- **`FIXES_SUMMARY.md`**: 三大根本问题的详细分析和修复方案
- **`OPTIMIZATION_SUCCESS_REPORT.md`**: 完整的优化成果报告（本文档）

### 诊断文档
- **`analysis/未进化修改意见1109.md`**: 原始问题诊断（中文）
- **`analysis/alphatuner.md`**: AlphaTuner 成功案例分析
- **`analysis/autotuner_config.yaml`**: 成功的参数优化配置示例

### Prompt 修复（核心）
- **`config/prompts/system_message.txt`**: 添加维度预算约束的错误/正确示例
- **`config/prompts/diff_user.txt`**: 添加约束违反警告和安全优化策略
- **`config/prompts/fragments.json`**: 添加诊断提示信息

### 代码修复
- **`src/timeloop_interface.py`**: 修复并行评估文件竞争（每个程序独立输出目录）
- **`src/evaluator_v2.py`**: 提取 program_id 并传递给 TimeloopInterface
- **`openevolve/process_parallel.py`**: 添加 no-op diff 验证（在上游 openevolve 仓库）

### 配置文件
- **`config/config_deepseek_r1_CLEAN.yaml`**: 
  - `max_tokens: 65536` (DeepSeek API 限制)
  - `num_top_programs: 5`, `num_diverse_programs: 5` (AlphaTuner 策略)

### 测试脚本
- **`run_optimized_test.sh`**: 一键运行优化测试（20 次迭代）

---

## 🔧 修复的三大问题

### 1. 维度预算约束说明不清晰 (CRITICAL)

**问题**: DeepSeek 不理解多层协同的维度预算约束

**症状**:
```
Dimension P: expected 224, got 1344
Dimension Q: expected 224, got 6272
```

**原因**: 
- LLM 修改了 GlobalBuffer temporal tiles (P=14, Q=16)
- 添加了 DummyBuffer spatial parallelism (P=2, Q=7)
- 但没有相应调整 DRAM temporal tiles
- 结果: P_total = 14×2×... ≠ 224

**修复**:
- 在 `system_message.txt` 中添加错误 vs 正确示例
- 明确公式: Π(所有层的 temporal×spatial) = 原始维度
- 强调规则: 修改任何层都必须调整 DRAM

### 2. 并行评估文件竞争 (已在之前 commit 修复)

**问题**: 4 个并行 worker 写入同一个 `generated_mapping.yaml`

**修复**: 
- TimeloopInterface 接受 `program_id` 参数
- 每个程序使用独立目录: `outputs/mappings/{program_id}/`

### 3. No-op Diff 验证缺失 (已在上游 openevolve 修复)

**问题**: apply_diff() 失败时不报错，生成重复程序

**修复**:
- 验证 `child_code != parent.code`
- 失败时返回明确错误信息

---

## 🚀 如何使用

### 运行优化测试

```bash
cd /root/evolve_1108/cc_1108
bash run_optimized_test.sh
```

这将运行 20 次迭代的演化测试。

### 检查结果

```bash
# 查看生成的程序
ls -la outputs/evolution/eyeriss_CLEAN_START/programs/

# 查看最优程序
cat outputs/evolution/eyeriss_CLEAN_START/best/best_program.py

# 分析 EDP 分布
python -c "
import json, os
programs_dir = 'outputs/evolution/eyeriss_CLEAN_START/programs/'
edp_values = []
for f in os.listdir(programs_dir):
    if f.endswith('.json'):
        with open(os.path.join(programs_dir, f)) as fp:
            prog = json.load(fp)
            edp = prog.get('metrics', {}).get('edp', 0)
            if edp > 0 and edp < 1e10:
                edp_values.append(edp)
print('EDP 分布:', sorted(set(edp_values)))
"
```

---

## 📊 DeepSeek 的优化策略

最优程序实现的三大优化：

### 1. GlobalBuffer Temporal Tiling 翻倍
```python
Baseline: {'K': 4, 'P': 7, 'Q': 8}
Best:     {'K': 8, 'P': 14, 'Q': 16}  # 全部翻倍
```
**效果**: 
- Tile 容量 8 倍提升 (224 → 1792 elements)
- DRAM 访问减少 112 倍
- 这是 Latency 降低 92% 的主要原因

### 2. DummyBuffer Spatial Parallelism
```python
Baseline: {'P': 1, 'Q': 1}
Best:     {'P': 2, 'Q': 7}  # 14 PEs 并行
```
**效果**:
- 激活 14 个 PE 进行并行计算
- 进一步降低 Latency
- **关键**: 正确调整了 DRAM 以保持维度预算

### 3. GlobalBuffer Bypass Weights
```python
Baseline: []
Best:     ['Weights']
```
**效果**:
- 理论上节省 GlobalBuffer 能量
- 实际 Energy 未降低（被其他因素抵消）
- 但总体 EDP 仍大幅改进

---

## 🔍 关键洞察

### DRAM 访问是性能瓶颈

**Baseline DRAM tiles**: K=8, P=32, Q=28  
访问次数 ∝ 8×32×28 = **7,168**

**Optimized DRAM tiles**: K=4, P=8, Q=2  
访问次数 ∝ 4×8×2 = **64**

**改进**: 7168 / 64 = **112 倍减少**

### 维度预算的正确维护

```
层级            P_temporal  P_spatial  Q_temporal  Q_spatial
-------------------------------------------------------------
PsumRegFile         1          1           1          1
WeightRegFile       1          1           1          1
InputRegFile        1          1           1          1
DummyBuffer         1          2           1          7      ← 空间并行
GlobalBuffer       14          1          16          1      ← 翻倍tiling
DRAM                8          1           2          1      ← 自动调整

验证: P = 1×1×1×1×2×14×1×8×1 = 224 ✓
     Q = 1×1×1×1×7×1×16×1×2 = 224 ✓
```

DeepSeek 成功理解了多层协同约束，自动调整 DRAM 层以满足预算。

---

## 📚 对比 AlphaTuner 成功经验

| AlphaTuner 策略 | 本项目应用 | 效果 |
|----------------|-----------|------|
| 大上下文 (128k) | 65k (DeepSeek 限制) | ✓ 理解复杂约束 |
| 5+5 采样 | 5 top + 5 diverse | ✓ 学习演化历史 |
| 系统参数探索 | temporal→spatial→bypass | ✓ 逐步优化 |
| 明确约束说明 | 错误/正确示例 | ✓ 违反率 10% |
| 失败反馈引导 | constraint_violation_hint | ✓ 自动修正 |

---

## 🎓 学到的经验

### Prompt Engineering 的重要性

**约束说明的质量直接决定演化成功率**

- ❌ 简单描述: "维度预算必须满足" → 100% 违反率
- ✅ 具体示例: 错误案例 + 正确案例 + 公式 → 10% 违反率

### LLM 可以处理复杂的硬件约束

DeepSeek-R1 成功：
- 理解了 6 层内存层次的协同约束
- 正确维护了 7 个维度的预算公式
- 探索了 temporal/spatial/bypass 多种优化策略
- 发现了 92% 的性能改进

### 演化需要迭代时间

- **短期** (1-10 迭代): 探索 temporal tiling
- **中期** (11-20 迭代): 引入 spatial parallelism
- **成果**: 第 16 次迭代发现最优解

---

## 🔗 相关链接

- **GitHub 仓库**: https://github.com/woodrains/AlphaEvovle
- **OpenEvolve 框架**: https://github.com/anthropics/openevolve
- **Timeloop 仿真器**: https://github.com/NVlabs/timeloop
- **Eyeriss 论文**: "Eyeriss: An Energy-Efficient Reconfigurable Accelerator for Deep Convolutional Neural Networks"

---

## 📝 引用

如果这个工作对你有帮助，请引用：

```bibtex
@misc{eyeriss_optimization_2025,
  title={Eyeriss Mapping Optimization via LLM-based Evolution},
  author={Claude Code Assistant},
  year={2025},
  howpublished={\url{https://github.com/woodrains/AlphaEvovle/tree/eyeriss-optimization-success-v1}}
}
```

---

**创建时间**: 2025-01-09  
**LLM**: DeepSeek-R1 (deepseek-reasoner)  
**框架**: OpenEvolve + Timeloop  
**成果**: 92% EDP 改进 🎉
