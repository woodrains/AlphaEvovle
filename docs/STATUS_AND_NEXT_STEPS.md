# Soter Timeloop Mapping Evolution - Status and Next Steps

**Date**: 2025-11-08
**Goal**: Enable full OpenEvolve evolution for Soter Timeloop mapping optimization

## ✅ Completed Work

### 1. Environment Setup ✅
- ✅ Created Python 3.10 conda environment (`openevolve_env`)
- ✅ Installed OpenEvolve framework successfully
- ✅ Configured Timeloop paths (v2.0 from `/root/Soter_v4/Soter_v4/timeloop-v2.0`)
- ✅ Set up GLM-4.6 API integration

### 2. Configuration Files ✅
- ✅ Fixed `config.yaml` to work with OpenEvolve API
- ✅ Created `prompts/system_message.txt` (Soter-specific)
- ✅ Created `prompts/fragments.json`
- ✅ Set up proper database, LLM, and evaluator configurations

### 3. Application Layer Complete ✅
- ✅ `initial_program.py` - SoterMappingGenerator with EVOLVE-BLOCK (lines 109-213)
- ✅ `evaluator.py` - Cascade evaluation (Stage1: constraints, Stage2: Timeloop)
- ✅ `constraint_checker.py` - C_t, C_p validation
- ✅ `run_evolution.sh` - Complete execution script

## ❌ Current Blocking Issue

### Problem: Timeloop Mapping Format Mismatch

**Error**: `ERROR: target storage level not found: PE`

**Root Cause**: The `initial_program.py` is generating incorrect target names in the mapping YAML.

**Current (Wrong)**:
```yaml
mapping:
- target: PE          # ❌ Wrong - "PE" doesn't exist
- target: Dummy       # ❌ Wrong - should be "DummyBuffer"
- target: GlobalBuffer  # ✅ Correct
- target: DRAM        # ✅ Correct
```

**Should Be (Correct)** - based on Soter's working examples:
```yaml
mapping:
- target: PsumRegFile     # ✅ Actual buffer name
  type: temporal
- target: WeightRegFile   # ✅ Actual buffer name
  type: temporal
- target: InputRegFile    # ✅ Actual buffer name
  type: temporal
- target: DummyBuffer     # ✅ Correct name
  type: temporal
- target: DummyBuffer
  type: spatial           # ✅ Spatial mapping
- target: GlobalBuffer
  type: temporal
- target: GlobalBuffer
  type: spatial
- target: DRAM
  type: temporal
```

### Key Insights from Working Soter Examples

From `/root/Soter_v4/Soter_v4/Soter/SpatialAccelerators/Eyeriss/report/eyeriss/sampled_episodes_32/deepbench_input1/layer-0/map.yaml`:

1. **Three RegFiles at PE level**:
   - `InputRegFile` (stores inputs/activations)
   - `WeightRegFile` (stores weights)
   - `PsumRegFile` (stores partial sums/outputs)

2. **Buffer Hierarchy** (from innermost to outermost):
   - Level 0: `InputRegFile`, `WeightRegFile`, `PsumRegFile`
   - Level 1: `DummyBuffer` (16 instances)
   - Level 2: `GlobalBuffer`
   - Level 3: `DRAM`

3. **Datatype Bypass**: Each level specifies which data to keep/bypass

## 🔧 Required Fixes

### Fix 1: Update `initial_program.py` Buffer Hierarchy

**Change in `_parse_buffer_hierarchy()` (line ~51)**:
```python
def _parse_buffer_hierarchy(self) -> List[str]:
    """解析缓存层级（从Soter的get_buffer_info）"""
    # OLD (Wrong):
    # return ["PE", "Dummy", "GlobalBuffer", "DRAM"]

    # NEW (Correct) - Three separate PE-level reg files:
    return [
        "PsumRegFile",      # PE level - partial sums
        "WeightRegFile",    # PE level - weights
        "InputRegFile",     # PE level - inputs
        "DummyBuffer",      # Level 1
        "GlobalBuffer",     # Level 2
        "DRAM"              # Level 3
    ]
```

### Fix 2: Update `convert_to_timeloop_mapping()` (line ~213)

Need to generate proper mapping with:
- Temporal and spatial factors
- Datatype bypass specifications
- Proper permutation format (e.g., "RSPQNKC")

**Template**:
```python
def convert_to_timeloop_mapping(self, strategy: Dict[str, Any]) -> Dict:
    mapping = {"mapping": []}

    for level_strategy in strategy["levels"]:
        level_name = level_strategy["level_name"]

        # Temporal mapping
        factors_str = " ".join([
            f"{dim}={size}"
            for dim, size in level_strategy["temporal_tiles"].items()
        ])
        perm_str = "".join(level_strategy["dimension_order"])

        mapping["mapping"].append({
            "target": level_name,
            "type": "temporal",
            "factors": factors_str,
            "permutation": perm_str
        })

        # Spatial mapping (if applicable)
        spatial_tiles = level_strategy["spatial_tiles"]
        if any(v > 1 for v in spatial_tiles.values()):
            spatial_factors = " ".join([
                f"{dim}={size}"
                for dim, size in spatial_tiles.items() if size > 1
            ])
            mapping["mapping"].append({
                "target": level_name,
                "type": "spatial",
                "factors": spatial_factors
            })

        # Datatype bypass (optional but recommended)
        # TODO: Add datatype bypass logic based on Soter examples

    return mapping
```

### Fix 3: Update Buffer Size Constraints

**Change in `_parse_buffer_sizes()` (line ~54)**:
```python
def _parse_buffer_sizes(self) -> Dict[str, int]:
    """解析各层缓存容量（C_t约束）"""
    # Match architecture file sizes
    return {
        "InputRegFile": 3 * 64 * 16 // 8,      # 3 depth * 64 width * 16 bits / 8
        "WeightRegFile": 48 * 64 * 16 // 8,    # 48 depth * 64 width
        "PsumRegFile": 4 * 64 * 16 // 8,       # 4 depth * 64 width
        "DummyBuffer": 0,                       # 0 depth (pass-through)
        "GlobalBuffer": 32768 * 64 * 16 // 8,  # 32768 depth * 64 width
        "DRAM": 1024 * 1024 * 1024              # 1GB
    }
```

## 📋 Next Steps (Priority Order)

### Step 1: Fix initial_program.py [CRITICAL - 30 mins]
1. Update buffer hierarchy to use correct names
2. Fix convert_to_timeloop_mapping() method
3. Test: `python initial_program.py` → should generate valid YAML

### Step 2: Verify with Timeloop [HIGH - 15 mins]
```bash
cd /root/evolve_1108/cc_1108
export PATH=/root/Soter_v4/Soter_v4/timeloop-v2.0/bin:$PATH
export LD_LIBRARY_PATH=/root/Soter_v4/Soter_v4/timeloop-v2.0/lib:$LD_LIBRARY_PATH

# Test Timeloop directly
timeloop-model \
  in_config/eyeriss.yaml \
  in_config/problem.yaml \
  in_config/generated_mapping.yaml
```

### Step 3: Test Evaluator [HIGH - 15 mins]
```bash
source /root/miniconda3/etc/profile.d/conda.sh
conda activate openevolve_env
export PATH=/root/Soter_v4/Soter_v4/timeloop-v2.0/bin:$PATH
export LD_LIBRARY_PATH=/root/Soter_v4/Soter_v4/timeloop-v2.0/lib:$LD_LIBRARY_PATH

python evaluator.py
```

Should see:
- ✅ Stage 1 passed: 1.0
- ✅ Stage 2 passed: 1.0
- ✅ Metrics: {latency: X, energy: Y, edp: Z}

### Step 4: Run Single-Iteration Evolution [MEDIUM - 1 hour]
```bash
./run_evolution.sh 1 DEBUG
```

### Step 5: Run Full Evolution [LOW - 4-8 hours]
```bash
./run_evolution.sh 50 INFO
```

## 📚 Reference Files

### Working Examples (for reference)
- `/root/Soter_v4/Soter_v4/Soter/SpatialAccelerators/Eyeriss/report/eyeriss/sampled_episodes_32/deepbench_input1/layer-0/`
  - `map.yaml` - Working mapping example
  - `arch.yaml` - Architecture definition
  - `problem.yaml` - Problem specification

### Eyeriss Architecture
- `/root/evolve_1108/cc_1108/in_config/eyeriss.yaml`
  - Line 42-82: PE RegFiles definition
  - Line 32-40: DummyBuffer definition
  - Line 21-31: GlobalBuffer definition
  - Line 9-15: DRAM definition

## 🎯 Success Criteria

### Minimal Success (Can proceed with evolution)
- [x] OpenEvolve installed
- [x] Config.yaml loads successfully
- [ ] Initial_program.py generates valid Timeloop mapping
- [ ] Timeloop runs without errors
- [ ] Evaluator returns metrics (latency, energy, edp)
- [ ] Single iteration completes

### Full Success (Production-ready)
- [ ] 50-iteration evolution completes
- [ ] Best program shows improvement over baseline
- [ ] Artifacts provide useful feedback to LLM
- [ ] Constraint violations handled correctly
- [ ] Results reproducible

## 🚀 Quick Start Commands

```bash
# Activate environment
source /root/miniconda3/etc/profile.d/conda.sh
conda activate openevolve_env

# Set Timeloop paths
export PATH=/root/Soter_v4/Soter_v4/timeloop-v2.0/bin:$PATH
export LD_LIBRARY_PATH=/root/Soter_v4/Soter_v4/timeloop-v2.0/lib:$LD_LIBRARY_PATH

# Change to project directory
cd /root/evolve_1108/cc_1108

# Run single iteration test
./run_evolution.sh 1 DEBUG

# Run full evolution
./run_evolution.sh 50 INFO
```

## 💡 Key Design Decisions

### Why Not Copy OpenEvolve Source?
- OpenEvolve is a framework (28 files, complex dependencies)
- cc_1108 should be application-layer (like MLX example)
- Maintains upgradeability and compatibility

### Why Cascade Evaluation?
- Stage 1: Fast constraint checking (< 5s) filters invalid mappings
- Stage 2: Timeloop evaluation (< 5min) only for valid mappings
- Saves ~90% of evaluation time by early rejection

### Why GLM-4.6?
- Chinese API, readily available
- OpenAI-compatible interface
- Good performance for code generation tasks

---

**Last Updated**: 2025-11-08
**Status**: Ready for Fix #1 (initial_program.py buffer names)
