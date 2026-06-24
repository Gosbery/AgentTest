"""
CLI entry point for the Agent.

Starts an interactive loop, delegates all work to agent.run_agent().
"""

import sys
import io

# Force UTF-8 output on Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from agent import run_agent, reset_conversation


def main():
    print("Agent started. Type your task, enter 'exit' to quit.")
    print("Type 'reset' to clear conversation history.\n")

    while True:
        try:
            user_input = input("\nUser> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if user_input.strip().lower() in ("exit", "quit", "q"):
            break

        if user_input.strip().lower() == "reset":
            reset_conversation()
            continue

        answer = run_agent(user_input)
        print(f"\nAssistant>\n{answer}")


if __name__ == "__main__":
    main()
