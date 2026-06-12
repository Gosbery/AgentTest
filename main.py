"""
CLI entry point for the Agent.

Starts an interactive loop, delegates all work to agent.run_agent().
"""

from agent import run_agent


def main():
    print("Agent started. Type your task, enter 'exit' to quit.\n")

    while True:
        try:
            user_input = input("\nUser> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if user_input.strip().lower() in ("exit", "quit", "q"):
            break

        answer = run_agent(user_input)
        print(f"\nAssistant>\n{answer}")


if __name__ == "__main__":
    main()
