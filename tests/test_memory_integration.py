"""
Memory integration test — 多轮对话测试记忆累积和加载。

测试场景：
1. 告诉 Agent 偏好 tabs 缩进
2. 让 Agent 创建 Python 文件，观察是否用 tabs
3. 询问 Agent 是否记得偏好
4. 添加新的偏好（单引号）
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

from agent import run_agent, reset_conversation
from agent.memory.storage import list_memory_files, MEMORY_DIR


def print_separator(title: str):
    """打印分隔线。"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


def print_memory_status():
    """打印当前记忆状态。"""
    print("\n[Memory Status]")
    files = list_memory_files()
    if not files:
        print("  No memories stored yet.")
    else:
        print(f"  Total memories: {len(files)}")
        for f in files:
            print(f"    - [{f['type']}] {f['name']}: {f['description']}")
    print()


def test_memory_accumulation():
    """测试记忆累积和加载。"""
    
    # 清理之前的记忆
    if MEMORY_DIR.exists():
        for f in MEMORY_DIR.glob("*.md"):
            if f.name != "MEMORY.md":
                f.unlink()
        print("[Cleanup] Cleared previous memories")
    
    # 重置对话
    reset_conversation()
    
    # =========================================================================
    # 第 1 轮：告诉 Agent 偏好 tabs
    # =========================================================================
    print_separator("Round 1: Tell Agent about tab preference")
    
    prompt1 = "I prefer using tabs for indentation, not spaces. Remember that."
    print(f"User> {prompt1}")
    print()
    
    answer1 = run_agent(prompt1)
    print(f"\nAssistant>\n{answer1}")
    
    print_memory_status()
    
    # =========================================================================
    # 第 2 轮：让 Agent 创建 Python 文件，观察是否用 tabs
    # =========================================================================
    print_separator("Round 2: Create Python file (observe tab usage)")
    
    prompt2 = "Create a Python file called test.py with a simple function."
    print(f"User> {prompt2}")
    print()
    
    answer2 = run_agent(prompt2)
    print(f"\nAssistant>\n{answer2}")
    
    # 检查是否创建了文件
    test_file = Path("test.py")
    if test_file.exists():
        content = test_file.read_text(encoding='utf-8')
        print(f"\n[File Check] test.py content (first 500 chars):")
        print("-" * 70)
        print(content[:500])
        print("-" * 70)
        
        # 检查是否使用了 tabs
        if '\t' in content:
            print("✓ SUCCESS: File contains tabs (\\t)")
        else:
            print("✗ WARNING: File does not contain tabs")
        
        # 清理测试文件
        test_file.unlink()
        print("[Cleanup] Deleted test.py")
    
    print_memory_status()
    
    # =========================================================================
    # 第 3 轮：询问 Agent 是否记得偏好
    # =========================================================================
    print_separator("Round 3: Ask Agent about preferences")
    
    prompt3 = "What did I tell you about my preferences?"
    print(f"User> {prompt3}")
    print()
    
    answer3 = run_agent(prompt3)
    print(f"\nAssistant>\n{answer3}")
    
    # 检查回答中是否提到 tabs
    if 'tab' in answer3.lower():
        print("\n✓ SUCCESS: Agent remembered tab preference")
    else:
        print("\n✗ WARNING: Agent may not have remembered tab preference")
    
    print_memory_status()
    
    # =========================================================================
    # 第 4 轮：添加新的偏好（单引号）
    # =========================================================================
    print_separator("Round 4: Add new preference (single quotes)")
    
    prompt4 = "I also prefer single quotes over double quotes for strings."
    print(f"User> {prompt4}")
    print()
    
    answer4 = run_agent(prompt4)
    print(f"\nAssistant>\n{answer4}")
    
    print_memory_status()
    
    # =========================================================================
    # 最终总结
    # =========================================================================
    print_separator("Test Summary")
    
    files = list_memory_files()
    print(f"Total memories stored: {len(files)}")
    for f in files:
        print(f"  - [{f['type']}] {f['name']}")
    
    print("\n" + "=" * 70)
    print("  Test completed!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    print("=" * 70)
    print("  Memory Integration Test")
    print("  Testing: Multi-turn conversation with memory accumulation")
    print("=" * 70)
    
    try:
        test_memory_accumulation()
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
