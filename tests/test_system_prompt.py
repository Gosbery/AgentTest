"""
Test script for s10_system_prompt module.

This script demonstrates:
1. Section loading based on context
2. Cache hit behavior
3. Dynamic memory section loading
"""

import sys
import io
from pathlib import Path

# Force UTF-8 output on Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.prompt_sections import (
    get_system_prompt,
    update_context,
    PROMPT_SECTIONS,
)


def test_basic_assembly():
    """Test basic prompt assembly with default context."""
    print("=" * 60)
    print("Test 1: Basic prompt assembly")
    print("=" * 60)
    
    context = update_context()
    prompt = get_system_prompt(context)
    
    print(f"\nPrompt length: {len(prompt)} characters")
    print(f"\nFirst 500 characters:\n{prompt[:500]}")
    print("\n")


def test_cache_hit():
    """Test cache hit when context unchanged."""
    print("=" * 60)
    print("Test 2: Cache hit behavior")
    print("=" * 60)
    
    context1 = update_context()
    prompt1 = get_system_prompt(context1)
    
    print("\nSecond call with same context:")
    prompt2 = get_system_prompt(context1)
    
    assert prompt1 == prompt2, "Cache should return same prompt"
    print("\n")


def test_memory_section():
    """Test memory section loading."""
    print("=" * 60)
    print("Test 3: Memory section loading")
    print("=" * 60)
    
    # Context without memory
    context_no_mem = {
        "enabled_tools": ["read_file", "write_file"],
        "workspace": "/test",
        "memories": "",
    }
    print("\nContext without memory:")
    prompt1 = get_system_prompt(context_no_mem)
    
    # Context with memory
    context_with_mem = {
        "enabled_tools": ["read_file", "write_file"],
        "workspace": "/test",
        "memories": "<memory-index>\n- user-preference-tabs — User prefers tabs\n</memory-index>",
    }
    print("\nContext with memory:")
    prompt2 = get_system_prompt(context_with_mem)
    
    assert "<memory-index>" in prompt2, "Memory section should be present"
    assert "<memory-index>" not in prompt1, "Memory section should not be present"
    print("\n")


def test_skills_section():
    """Test skills section loading."""
    print("=" * 60)
    print("Test 4: Skills section loading")
    print("=" * 60)
    
    context = update_context()
    prompt = get_system_prompt(context)
    
    # Check if skills section is present (depends on whether skills exist)
    if context.get("skills"):
        assert "<skills>" in prompt, "Skills section should be present"
        print("\nSkills section is present")
    else:
        print("\nNo skills available, skills section not loaded")
    
    print("\n")


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("s10_system_prompt Test Suite")
    print("=" * 60 + "\n")
    
    test_basic_assembly()
    test_cache_hit()
    test_memory_section()
    test_skills_section()
    
    print("=" * 60)
    print("All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
