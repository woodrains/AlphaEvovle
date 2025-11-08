#!/usr/bin/env python3
"""
Prompt系统验证脚本 - 测试 cc_1108 的 prompt 模板是否正确配置
"""

import os
import sys
import yaml
from pathlib import Path

def validate_prompt_templates():
    """验证所有必需的 prompt 模板文件"""
    print("=" * 80)
    print("🔍 PROMPT TEMPLATE VALIDATION")
    print("=" * 80)

    prompts_dir = Path("/root/evolve_1108/cc_1108/prompts")

    # 必需的模板文件
    required_templates = [
        "system_message.txt",
        "diff_user.txt",
        "full_rewrite_user.txt",
        "evolution_history.txt",
        "previous_attempt.txt",
        "top_program.txt",
        "inspiration_program.txt",
        "inspirations_section.txt",
        "fragments.json"
    ]

    missing_files = []
    valid_files = []

    print("\n📁 Checking template files...")
    for template in required_templates:
        filepath = prompts_dir / template
        if filepath.exists():
            size = filepath.stat().st_size
            lines = len(filepath.read_text().splitlines())
            print(f"  ✅ {template:30s} ({lines:4d} lines, {size:5d} bytes)")
            valid_files.append(template)
        else:
            print(f"  ❌ {template:30s} MISSING")
            missing_files.append(template)

    if missing_files:
        print(f"\n❌ FAILED: {len(missing_files)} missing template(s)")
        return False

    print(f"\n✅ All {len(required_templates)} required templates found")
    return True


def validate_config():
    """验证 config.yaml 的 prompt 配置"""
    print("\n" + "=" * 80)
    print("🔍 CONFIG.YAML VALIDATION")
    print("=" * 80)

    config_path = Path("/root/evolve_1108/cc_1108/config.yaml")

    if not config_path.exists():
        print("❌ config.yaml not found")
        return False

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    print("\n📝 Checking prompt configuration...")

    # 检查 prompt 配置
    if 'prompt' not in config:
        print("  ❌ 'prompt' section missing")
        return False

    prompt_config = config['prompt']

    # 检查模板目录
    template_dir = prompt_config.get('template_dir')
    if not template_dir:
        print("  ❌ 'template_dir' not specified")
        return False

    print(f"  ✅ template_dir: {template_dir}")

    # 检查其他配置项
    checks = {
        "num_top_programs": int,
        "num_inspirations": int,
        "include_artifacts": bool,
        "max_artifact_bytes": int,
    }

    for key, expected_type in checks.items():
        value = prompt_config.get(key)
        if value is None:
            print(f"  ⚠️  {key}: not set (optional)")
        elif not isinstance(value, expected_type):
            print(f"  ❌ {key}: wrong type (expected {expected_type.__name__})")
            return False
        else:
            print(f"  ✅ {key}: {value}")

    print("\n📝 Checking database configuration...")

    # 检查 database 配置
    if 'database' not in config:
        print("  ❌ 'database' section missing")
        return False

    db_config = config['database']

    # 检查 feature_dimensions
    feature_dims = db_config.get('feature_dimensions')
    if not feature_dims:
        print("  ❌ 'feature_dimensions' not specified")
        return False

    if not isinstance(feature_dims, list):
        print("  ❌ 'feature_dimensions' must be a list")
        return False

    print(f"  ✅ feature_dimensions: {feature_dims}")

    # 检查采样策略配置
    sampling_checks = {
        "exploration_ratio": float,
        "exploitation_ratio": float,
        "migration_interval": int,
        "migration_rate": float,
    }

    for key, expected_type in sampling_checks.items():
        value = db_config.get(key)
        if value is None:
            print(f"  ⚠️  {key}: not set (will use default)")
        elif not isinstance(value, (int, float)) if expected_type == float else not isinstance(value, expected_type):
            print(f"  ❌ {key}: wrong type")
            return False
        else:
            print(f"  ✅ {key}: {value}")

    print("\n✅ Config validation passed")
    return True


def validate_template_content():
    """验证模板内容的占位符"""
    print("\n" + "=" * 80)
    print("🔍 TEMPLATE CONTENT VALIDATION")
    print("=" * 80)

    prompts_dir = Path("/root/evolve_1108/cc_1108/prompts")

    # 检查 diff_user.txt 的占位符
    print("\n📝 Checking diff_user.txt placeholders...")
    diff_user = (prompts_dir / "diff_user.txt").read_text()

    required_placeholders = [
        "{fitness_score}",
        "{feature_coords}",
        "{improvement_areas}",
        "{artifacts}",
        "{evolution_history}",
        "{current_program}",
        "{language}",
        "{feature_dimensions}"
    ]

    missing_placeholders = []
    for placeholder in required_placeholders:
        if placeholder in diff_user:
            print(f"  ✅ {placeholder}")
        else:
            print(f"  ❌ {placeholder} MISSING")
            missing_placeholders.append(placeholder)

    if missing_placeholders:
        print(f"\n❌ Missing placeholders in diff_user.txt")
        return False

    # 检查 full_rewrite_user.txt 的占位符
    print("\n📝 Checking full_rewrite_user.txt placeholders...")
    full_rewrite = (prompts_dir / "full_rewrite_user.txt").read_text()

    for placeholder in required_placeholders:
        if placeholder in full_rewrite:
            print(f"  ✅ {placeholder}")
        else:
            print(f"  ⚠️  {placeholder} not found (may be optional)")

    # 检查 fragments.json
    print("\n📝 Checking fragments.json...")
    import json
    fragments = json.loads((prompts_dir / "fragments.json").read_text())

    print(f"  ✅ {len(fragments)} fragment(s) defined")

    # 检查关键 fragment
    key_fragments = [
        "fitness_improved",
        "fitness_declined",
        "constraint_aware",
        "optimization_hints",
        "error_analysis"
    ]

    for fragment in key_fragments:
        if fragment in fragments:
            print(f"  ✅ {fragment}")
        else:
            print(f"  ❌ {fragment} MISSING")
            return False

    print("\n✅ Template content validation passed")
    return True


def main():
    """主验证流程"""
    print("\n" + "=" * 80)
    print("🔬 OpenEvolve Prompt System Validation for cc_1108")
    print("=" * 80)

    results = []

    # 1. 验证模板文件
    results.append(("Template Files", validate_prompt_templates()))

    # 2. 验证配置
    results.append(("Config.yaml", validate_config()))

    # 3. 验证模板内容
    results.append(("Template Content", validate_template_content()))

    # 总结
    print("\n" + "=" * 80)
    print("📊 VALIDATION SUMMARY")
    print("=" * 80)

    all_passed = True
    for name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{name:30s}: {status}")
        if not passed:
            all_passed = False

    print("=" * 80)

    if all_passed:
        print("\n🎉 All validations passed! Prompt system is ready.")
        print("\nNext steps:")
        print("  1. Run OpenEvolve with: python openevolve-run.py ...")
        print("  2. Monitor artifacts feedback in evolution logs")
        print("  3. Verify LLM receives constraint violation details")
        return 0
    else:
        print("\n❌ Some validations failed. Please fix the issues above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
