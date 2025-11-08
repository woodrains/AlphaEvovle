# Soter Timeloop Mapping Evolution - 项目结构

**项目目录**: `/root/evolve_1108/cc_1108`

## 📁 文件夹组织

```
cc_1108/
├── src/                          # 源代码 (不可修改的核心逻辑)
│   ├── initial_program.py        # 映射生成器 (含EVOLVE-BLOCK)
│   ├── evaluator.py              # Timeloop评估器 (cascade evaluation)
│   └── constraint_checker.py     # 约束检查器 (C_t/C_p验证)
│
├── config/                       # 配置文件 (可修改的参数)
│   ├── config.yaml               # OpenEvolve主配置
│   ├── timeloop/                 # Timeloop配置
│   │   ├── eyeriss.yaml          # Eyeriss架构定义
│   │   ├── problem.yaml          # 卷积层问题定义
│   │   └── mapspace.yaml         # 映射空间约束
│   └── prompts/                  # OpenEvolve提示模板
│       ├── system_message.txt    # Soter专用系统消息
│       ├── fragments.json        # 映射优化提示片段
│       └── *.txt                 # 其他提示模板
│
├── scripts/                      # 可执行脚本
│   ├── run_evolution.sh          # 主演化脚本 (推荐使用)
│   └── run_experiment.sh         # 实验脚本
│
├── outputs/                      # 所有输出文件 (自动生成，可清理)
│   ├── evolution/                # OpenEvolve演化输出
│   │   └── eyeriss_mapping_evolution/  # 数据库和checkpoint
│   ├── mappings/                 # 生成的映射文件
│   │   └── generated_mapping.yaml
│   └── timeloop_temp/            # Timeloop临时文件
│       ├── *.stats.txt           # 统计输出
│       ├── *.map.txt             # 映射详情
│       └── *.xml                 # XML统计
│
├── tests/                        # 测试文件
│   ├── test_openevolve_integration.py
│   └── validate_prompts.py
│
├── docs/                         # 文档
│   ├── README.md                 # 项目说明
│   ├── STATUS_AND_NEXT_STEPS.md  # 当前状态和下一步
│   ├── GAP_ANALYSIS.md           # OpenEvolve vs cc_1108对比
│   └── IMPLEMENTATION_CHECKLIST.md
│
└── .gitignore                    # Git忽略规则
```

## 🎯 关键路径说明

### 源代码 (`src/`)
- **不可修改**: 这些文件在演化过程中会被OpenEvolve读取和修改
- `initial_program.py` 的 EVOLVE-BLOCK (lines 107-210) 会被LLM优化
- 演化后的代码会保存在 `outputs/evolution/` 中

### 配置文件 (`config/`)
- **可修改**: 根据需要调整参数
- `config.yaml`: 修改演化策略、LLM参数、数据库设置
- `config/timeloop/`: 修改目标架构或问题规模

### 输出文件 (`outputs/`)
- **自动生成**: 所有运行时生成的文件都在这里
- **可安全清理**: `rm -rf outputs/*` 清理所有临时文件
- `outputs/evolution/`: OpenEvolve的checkpoint和最优程序
- `outputs/mappings/`: 每次运行生成的mapping YAML
- `outputs/timeloop_temp/`: Timeloop仿真的详细输出

## 🚀 使用方式

### 1. 运行单次迭代测试
```bash
cd /root/evolve_1108/cc_1108
bash scripts/run_evolution.sh 1 DEBUG
```

### 2. 运行完整演化 (50次迭代)
```bash
bash scripts/run_evolution.sh 50 INFO
```

### 3. 清理临时文件
```bash
# 清理所有输出
rm -rf outputs/timeloop_temp/*
rm -rf outputs/mappings/*

# 重置演化（谨慎！会删除所有进度）
rm -rf outputs/evolution/*
```

### 4. 查看演化结果
```bash
# 查看最优程序
cat outputs/evolution/eyeriss_mapping_evolution/best_program.py

# 查看演化轨迹
python -c "
import json
with open('outputs/evolution/eyeriss_mapping_evolution/trace.json') as f:
    trace = json.load(f)
    print(f'最优EDP: {trace[-1][\"best_edp\"]}')
"
```

## 📊 输出文件管理策略

### 保留的文件
- `outputs/evolution/`: **保留** - 包含演化进度和最优解
- `config/`: **保留** - 配置文件

### 可清理的文件
- `outputs/timeloop_temp/`: 每次运行后可删除
- `outputs/mappings/`: 保留最新的即可

### 自动清理 (在 `scripts/run_evolution.sh` 中)
```bash
# 演化开始前自动清理旧的临时文件
rm -rf outputs/timeloop_temp/*
```

## 🔧 路径配置

### 代码中的路径引用
```python
# src/initial_program.py
in_config_dir = Path(__file__).parent.parent / "config" / "timeloop"

# src/evaluator.py
self.in_config_dir = Path(__file__).parent.parent / "config" / "timeloop"
output_dir = Path(__file__).parent.parent / "outputs" / "mappings"
```

### OpenEvolve配置中的路径
```yaml
# config/config.yaml
prompt:
  template_dir: "/root/evolve_1108/cc_1108/config/prompts"

database:
  db_path: "./outputs/evolution/eyeriss_mapping_evolution"
```

## ⚠️ 注意事项

1. **不要手动修改 `outputs/` 下的文件**
   - 这些文件由程序自动生成和管理

2. **Git 管理**
   - `outputs/` 应该在 `.gitignore` 中
   - 只提交源代码、配置和文档

3. **演化中断后恢复**
   - OpenEvolve会自动从checkpoint恢复
   - 如需重新开始，删除 `outputs/evolution/`

4. **磁盘空间管理**
   - 每次Timeloop仿真生成 ~100KB 文件
   - 50次迭代约需 5-10MB
   - 定期清理 `outputs/timeloop_temp/`

## 📈 演化过程文件流

```
1. 启动 → scripts/run_evolution.sh
         ↓
2. OpenEvolve读取 → src/initial_program.py (EVOLVE-BLOCK)
                    config/config.yaml
                    config/prompts/
         ↓
3. LLM生成新代码 → 临时Python文件
         ↓
4. 评估器执行 → src/evaluator.py
                ↓
5. 生成映射 → outputs/mappings/generated_mapping.yaml
         ↓
6. Timeloop仿真 → outputs/timeloop_temp/*.stats.txt
         ↓
7. 保存结果 → outputs/evolution/eyeriss_mapping_evolution/
              - best_program.py
              - checkpoint_N.json
              - trace.json
```

## 🗂️ 文件清单

### 源代码 (3个)
- `src/initial_program.py` (293 lines)
- `src/evaluator.py` (599 lines)
- `src/constraint_checker.py` (167 lines)

### 配置文件 (5个)
- `config/config.yaml` (66 lines)
- `config/timeloop/eyeriss.yaml`
- `config/timeloop/problem.yaml`
- `config/timeloop/mapspace.yaml`
- `config/prompts/*.txt` (8个模板)

### 脚本 (2个)
- `scripts/run_evolution.sh`
- `scripts/run_experiment.sh`

### 文档 (6个)
- `docs/README.md`
- `docs/STATUS_AND_NEXT_STEPS.md`
- `docs/GAP_ANALYSIS.md`
- `docs/IMPLEMENTATION_CHECKLIST.md`
- `docs/openevolve_soter_adaptation_plan.md`
- `docs/prompt+database系统.md`

---

**最后更新**: 2025-11-08
**维护者**: Claude Code
