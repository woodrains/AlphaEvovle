深度理解分析报告
  一、OpenEvolve核心架构理解

  1. Prompt系统 (prompt/sampler.py + templates.py)

  核心设计思想:
  - TemplateManager: 级联模板系统,支持默认模板→自定义模板的覆盖机制
  - PromptSampler: 动态构建每轮演化的提示,包含:
    - current_program: 当前待优化的程序代码
    - evolution_history: 历史尝试(最近3个)
    - top_programs: 精英程序(最佳fitness,默认3个)
    - inspirations: 多样性启发程序(由num_diverse_programs控制)
    - improvement_areas: 基于fitness/feature的改进建议
    - artifacts: 上次执行的错误/警告反馈

  关键机制:
  # Fitness vs Feature分离
  fitness_score = get_fitness_score(metrics, feature_dimensions)
  # Fitness = 不包含feature_dimensions的指标平均值
  # Feature = 用于MAP-Elites网格定位的维度

  # Artifacts反馈循环
  artifacts_section = self._render_artifacts(program_artifacts)
  # 包含stderr、llm_feedback、build_warnings等,供LLM学习

  2. Program Database系统 (database.py)

  核心创新: MAP-Elites + Island Evolution

  # 三层存储结构:
  self.programs: Dict[str, Program]  # 所有程序
  self.islands: List[Set[str]]       # 岛屿隔离种群
  self.island_feature_maps: List[Dict[str, str]]  # 每个岛屿的MAP-Elites网格

  # Feature坐标计算
  feature_coords = self._calculate_feature_coords(program)
  # 例如: [complexity_bin, diversity_bin, custom_metric_bin]

  # 关键约束检查
  if not self._is_novel(program.id, island_idx):
      return  # Novelty rejection - 基于embedding相似度+LLM judge

  Island-based Evolution机制:
  - isolation: 每个岛屿独立演化,避免早熟收敛
  - migration: 每N代(migration_interval)进行环形拓扑迁移
  - 防止重复迁移: 标记migrant=True,避免指数级复制

  MAP-Elites网格更新:
  # 计算feature坐标 → 映射到网格cell
  feature_key = self._feature_coords_to_key(coords)

  # 只在fitness更好时替换
  if self._is_better(new_program, existing_program):
      island_feature_map[feature_key] = new_program.id

  3. 采样策略 (database.py的sample方法)

  # 三种采样模式的动态平衡
  rand = random.random()
  if rand < exploration_ratio:
      # EXPLORATION: 从当前岛屿随机采样
      parent = self._sample_exploration_parent()
  elif rand < exploration_ratio + exploitation_ratio:
      # EXPLOITATION: 从archive(精英集)采样
      parent = self._sample_exploitation_parent()
  else:
      # WEIGHTED: 按fitness加权采样
      parent = self._sample_random_parent()

  二、cc_1108适配方案的理解

  1. Initial Program结构

  # EVOLVE-BLOCK位置: line 109-213
  def generate_mapping_strategy(self) -> Dict[str, Any]:
      # 返回结构化映射决策
      strategy = {
          "meta": {...},
          "levels": [
              {
                  "level_name": "PE",
                  "dimension_order": ["R", "S", "P", ...],
                  "temporal_tiles": {"N": 1, "K": 1, ...},
                  "spatial_tiles": {"N": 1, "K": 1, ...},
                  "bypass": []
              },
              # ... 4层缓存层级
          ]
      }

  可演化的决策变量:
  - X_d (dimension_order): 维度遍历顺序,影响数据重用模式
  - X_t (temporal_tiles): 时间分块大小,受C_t约束
  - X_p (spatial_tiles): 空间并行度,受C_p约束
  - Bypass策略: 跳过哪些数据搬运

  2. Evaluator分层评估

  # Stage 1: 快速约束检查 (< 5秒)
  constraint_result = self._check_constraints_stage1(mapping_strategy)
  if not constraint_result["passed"]:
      return self._create_constraint_failure_result(constraint_result)

  # Stage 2: Timeloop完整评估 (< 5分钟)
  timeloop_result = self._run_timeloop_stage2(mapping_file)

  # Stage 3: 性能分析
  analysis = self._analyze_performance(metrics)

  关键设计:
  - 早期拒绝: 违反约束的程序在Stage1就被过滤,节省Timeloop时间
  - Artifacts反馈: 约束违反的详细信息传递给LLM:
  "artifacts": {
      "constraint_violations": [
          {
              "type": "buffer_capacity_exceeded",
              "level": "l1",
              "required": 65536,
              "available": 1024,
              "message": "Buffer size 1024 < required 65536"
          }
      ]
  }

  3. Constraint Checker实现

  # C_t约束: tile大小不超过缓存容量
  total_tile = input_tile + weight_tile + output_tile
  if total_tile > buffer_size:
      violations.append({...})

  # C_p约束: 空间分块不超过PE数量
  spatial_product = ∏(spatial_tiles)
  if spatial_product > spmap_cstr:
      violations.append({...})

  # 维度预算守恒
  total_tiles[dim] = ∏(temporal[dim] × spatial[dim])
  if total_tiles[dim] != original_dimension[dim]:
      violations.append({...})

  三、关键洞察和设计精妙之处

  1. Fitness vs Feature的哲学分离

  OpenEvolve将两者明确分开:
  - Fitness: 优化目标,不包含feature_dimensions
  - Feature: 搜索空间的多样性维度

  在Soter场景:
  # 推荐配置
  database:
    feature_dimensions: ["latency", "energy"]  # MAP-Elites网格维度
    # Fitness会使用EDP等综合指标

  这样设计的好处:
  - MAP-Elites网格按latency×energy展开,覆盖Pareto前沿
  - Fitness按EDP(energy×delay)优化,找到最佳权衡点

  2. Novelty Rejection机制

  # database.py:254-256
  if not self._is_novel(program.id, island_idx):
      logger.debug("Program failed novelty check")
      return  # 不添加到岛屿

  两阶段判断:
  1. Embedding相似度: 快速过滤代码几乎相同的程序
  2. LLM Judge: 对高相似度程序进行语义判断
  NOVELTY_USER_MSG = "Given existing code A and proposed code B,
                      are they substantially different? Answer: NOVEL or NOT NOVEL"

  3. Artifacts作为Side-Channel的妙用

  不同于直接返回错误信息,OpenEvolve将artifacts独立存储:
  - 小artifacts (< 32KB): 存储在JSON中
  - 大artifacts: 独立文件存储

  在Soter场景的应用:
  # evaluator.py返回
  "artifacts": {
      "constraint_violations": [...],  # 供LLM学习哪些约束违反了
      "timeloop_stats": {...},         # Timeloop详细统计
      "violation_summary": "..."       # 格式化的约束错误摘要
  }

  LLM在下一轮prompt中会看到:
  ## Last Execution Output
  ⚠️ buffer_capacity_exceeded at level l1
  Required: 65536, Available: 1024
  Suggestion: Reduce temporal tile sizes for C dimension

  4. MAP-Elites Cell替换的智慧

  # database.py:273-323
  if feature_key not in island_feature_map:
      logger.info("New MAP-Elites cell occupied")  # 新区域探索
  else:
      # Cell已占用,只在更好时替换
      if self._is_better(new_program, existing_program):
          logger.info("MAP-Elites cell improved")
          # 从岛屿移除旧程序,保持一致性
          self.islands[island_idx].discard(existing_program_id)

  关键细节: 替换时要从island set中移除旧程序,避免:
  - 岛屿累积大量stale程序
  - MAP-Elites网格和岛屿成员不一致

  四、对您实现的建议

  1. Feature Dimensions的选择

  建议使用2-3个维度:
  database:
    feature_dimensions: ["latency", "energy"]
    feature_bins:
      latency: 15  # 15×15=225个cell,适中的粒度
      energy: 15

  不推荐:
  feature_dimensions: ["mapping_diversity"]  # 过于抽象

  原因:
  - Timeloop本身返回latency/energy是连续值
  - MAP-Elites会自动binning
  - 这样能覆盖Pareto前沿

  2. Prompt Template定制

  创建prompts/system_message.txt:
  You are an expert in DNN accelerator mapping optimization for Eyeriss architecture.

  GOAL: Optimize the mapping strategy to minimize Energy-Delay Product (EDP).

  CRITICAL CONSTRAINTS (violations will cause immediate failure):
  1. C_t: Buffer capacity - tile size must fit in each level's buffer
  2. C_p: Spatial parallelism - spatial tiles ≤ PE count at each level
  3. Dimension budget: ∏(temporal × spatial) must equal original dimension

  OPTIMIZATION STRATEGIES:
  - Maximize data reuse by keeping frequently used data in inner buffers
  - Utilize spatial parallelism on P/Q dimensions (Eyeriss strength)
  - Avoid R/S spatial tiling (small kernel size, wastes PEs)
  - Inner loop should be R/S (Row Stationary dataflow)

  3. Baseline测量的重要性

  # evaluator.py:268-280
  if self.baseline_metrics is None:
      self._measure_baseline()  # 首次运行时测量

  注意: baseline应该是initial_program.py的保守策略,不能是随机的。这样改进百分比才有意义。

  五、潜在问题和优化方向

  1. Timeloop评估的超时问题

  如果映射非法,Timeloop可能hang:
  # evaluator.py:207
  result = subprocess.run(cmd, timeout=300)  # 5分钟超时

  优化建议:
  - Stage1的约束检查应该更严格
  - 可以添加"quick simulation"模式,先估算feasibility

  2. Island迁移的触发时机

  # database.py:1735-1737
  def should_migrate(self) -> bool:
      max_generation = max(self.island_generations)
      return (max_generation - self.last_migration_generation) >= migration_interval

  理解: 迁移基于generation计数,不是iteration计数。每个岛屿独立累积generation。

  对Soter的影响:
  - 如果Timeloop评估很慢,可能很久才migration一次
  - 可以考虑降低migration_interval(默认50 → 20)

  3. LLM Token消耗

  每轮prompt包含:
  - system_message
  - evolution_history (3个previous attempts)
  - top_programs (3个精英程序的完整代码)
  - inspirations (2个多样性程序)
  - artifacts

  估算: 如果initial_program.py有300行,每轮prompt可能:
  - system_message: 500 tokens
  - 8个程序代码: 8 × 1500 = 12000 tokens
  - history/artifacts: 2000 tokens
  - Total: ~15K tokens input

  对GLM-4.6的影响: 按0.1元/1M tokens计算,每轮约0.0015元,50轮约0.075元。可接受。

  ---
  总结

  OpenEvolve的核心优势在于:
  1. MAP-Elites + Islands: 多样性保持 + 并行探索
  2. Artifacts反馈: LLM从错误中学习
  3. 分层评估: 早期过滤无效程序
  4. Novelty rejection: 避免重复探索

  您的cc_1108实现很好地利用了这些机制,特别是:
  - Stage1约束检查: 快速过滤违反C_t/C_p的映射
  - Artifacts详细反馈: 告诉LLM哪些约束violated,如何修复
  - 结构化映射表示: 便于LLM理解和修改

  建议重点关注:
  1. Prompt的约束强调(避免LLM生成非法映射)
  2. Feature dimensions选择(latency + energy比mapping_diversity更好)
  3. Baseline策略的保守性(确保有改进空间)