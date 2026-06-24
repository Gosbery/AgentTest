#!/usr/bin/env python3
"""
Skill Loading 测试脚本 — 验证两层注入策略。

测试内容:
1. Layer 1: 系统 prompt 中是否包含 skill 菜单
2. Layer 2: load_skill 工具是否能返回完整 skill body
3. 不存在的 skill 是否返回错误信息
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.skill_loader import SkillLoader
from agent.tools.skill import make_load_skill, make_load_skill_schema


def test_layer1():
    """验证 Layer 1: skill descriptions 注入系统 prompt"""
    loader = SkillLoader()
    descs = loader.get_skill_descriptions()

    print("=" * 50)
    print("  Layer 1: Skill Menu (System Prompt)")
    print("=" * 50)
    assert len(descs) > 0, "No skills loaded"
    for name, desc in sorted(descs.items()):
        print(f"  - {name}: {desc}")
    print()
    assert "git" in descs
    assert "code-review" in descs
    assert "testing" in descs
    print("  PASS: All expected skills are present")
    print()


def test_layer2():
    """验证 Layer 2: load_skill 返回完整 body"""
    loader = SkillLoader()
    load_skill = make_load_skill(loader)

    print("=" * 50)
    print("  Layer 2: Load Skill Body (On Demand)")
    print("=" * 50)

    result = load_skill(name="git")
    print(f"  load_skill('git'):\n{result[:200]}...")
    print()
    assert '<skill name="git">' in result
    assert "Git Workflow" in result
    print("  PASS: Skill body returned with <skill> tags")
    print()

    # Test code-review
    result = load_skill(name="code-review")
    assert '<skill name="code-review">' in result
    assert "Code Review Checklist" in result
    print("  PASS: code-review skill works too")
    print()


def test_missing_skill():
    """验证不存在的 skill 返回错误"""
    loader = SkillLoader()
    load_skill = make_load_skill(loader)

    print("=" * 50)
    print("  Missing Skill Handling")
    print("=" * 50)

    result = load_skill(name="nonexistent")
    print(f"  load_skill('nonexistent'): {result}")
    assert "Error" in result
    assert "not found" in result
    print("  PASS: Error message returned for missing skill")
    print()


def test_schema():
    """验证 tool schema 是否正确"""
    loader = SkillLoader()
    schema = make_load_skill_schema(loader)

    print("=" * 50)
    print("  Tool Schema")
    print("=" * 50)
    print(f"  {schema}")
    assert schema["function"]["name"] == "load_skill"
    assert "name" in schema["function"]["parameters"]["properties"]
    print("  PASS: Schema is valid")
    print()


if __name__ == "__main__":
    test_layer1()
    test_layer2()
    test_missing_skill()
    test_schema()
    print("All skill loading tests passed!")
