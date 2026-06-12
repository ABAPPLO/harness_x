#!/usr/bin/env python3
"""
harness_x — Core AI Agent Framework

Usage:
    python __main__.py                            # Interactive chat
    python __main__.py chat -q "Hello"            # One-shot query
    python __main__.py doctor                     # Diagnose setup issues
    HARNESS_HOME=~/.harness_x python __main__.py  # Custom home directory
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root (where this file lives) is on sys.path so that
# top-level modules like run_agent, harness_constants, etc. are importable
# regardless of how the script is invoked.
_PROJECT_ROOT = str(Path(__file__).resolve().parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def main() -> None:
    """Main entry point for harness_x."""
    # Windows UTF-8 bootstrap — no-op on POSIX
    try:
        import harness_bootstrap  # noqa: F401
    except ModuleNotFoundError:
        pass

    from harness_constants import get_harness_home

    home = get_harness_home()
    home.mkdir(parents=True, exist_ok=True)

    argv = sys.argv[1:]

    if not argv:
        _interactive_chat()
        return

    command = argv[0]
    rest = argv[1:]

    if command in ("chat",):
        _handle_chat(rest)
    elif command in ("doctor",):
        _handle_doctor(rest)
    elif command in ("--help", "-h", "help"):
        _print_help()
    elif command in ("--version", "-V", "version"):
        _print_version()
    else:
        # Treat unknown commands as a direct query (one-shot mode)
        _handle_chat(["-q", " ".join(argv)])


def _interactive_chat() -> None:
    """Launch interactive chat session."""
    try:
        from run_agent import AIAgent
        from harness_cli.config import load_config
    except ImportError as exc:
        print(f"Error loading harness_x modules: {exc}", file=sys.stderr)
        print("Make sure dependencies are installed: pip install -e .", file=sys.stderr)
        sys.exit(1)

    config = load_config()
    agent = AIAgent(
        base_url=config.get("base_url", ""),
        model=config.get("model", "gpt-4o"),
        api_key=config.get("api_key", ""),
    )

    print("harness_x — Core AI Agent Framework")
    print(f"  Model: {agent.model}")
    print(f"  Home:  {os.environ.get('HARNESS_HOME', '~/.harness_x')}")
    print("  Type 'exit' or Ctrl+D to quit\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        if user_input.lower() in ("exit", "quit", "q"):
            break
        if not user_input:
            continue
        try:
            response = agent.run_conversation(user_input)
            print(f"\nAgent: {response}\n")
        except Exception as exc:
            print(f"\nError: {exc}\n", file=sys.stderr)


def _handle_chat(args: list[str]) -> None:
    """Handle the chat subcommand (interactive or one-shot)."""
    import argparse

    parser = argparse.ArgumentParser(prog="harness_x chat", description="Chat with the agent")
    parser.add_argument("-q", "--query", type=str, help="One-shot query (skip interactive mode)")
    parser.add_argument("--model", type=str, help="Model override")
    parser.add_argument("--base-url", type=str, help="API base URL override")
    parsed = parser.parse_args(args)

    try:
        from run_agent import AIAgent
        from harness_cli.config import load_config
    except ImportError as exc:
        print(f"Error loading harness_x modules: {exc}", file=sys.stderr)
        sys.exit(1)

    config = load_config()
    model = parsed.model or config.get("model", "gpt-4o")
    base_url = parsed.base_url or config.get("base_url", "")

    agent = AIAgent(base_url=base_url, model=model, api_key=config.get("api_key", ""))

    if parsed.query:
        # One-shot mode
        try:
            response = agent.run_conversation(parsed.query)
            print(response)
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        # Interactive mode
        print("harness_x — Chat Session")
        print(f"  Model: {model}")
        print("  Type 'exit' or Ctrl+D to quit\n")
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye!")
                break
            if user_input.lower() in ("exit", "quit", "q"):
                break
            if not user_input:
                continue
            try:
                response = agent.run_conversation(user_input)
                print(f"\nAgent: {response}\n")
            except Exception as exc:
                print(f"\nError: {exc}\n", file=sys.stderr)


def _handle_doctor(args: list[str]) -> None:
    """Diagnose common setup issues."""
    from pathlib import Path

    checks: list[tuple[str, bool, str]] = []

    # 1. Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info >= (3, 11)
    checks.append(("Python version", py_ok, f"{py_ver} (requires >=3.11)"))

    # 2. Home directory
    try:
        from harness_constants import get_harness_home
        home = get_harness_home()
        home_ok = home.exists()
        checks.append(("Home directory", home_ok, str(home)))
    except Exception as exc:
        checks.append(("Home directory", False, str(exc)))

    # 3. Config file
    try:
        config_path = home / "config.yaml"
        config_ok = config_path.exists()
        checks.append(("Config file", config_ok, str(config_path)))
    except NameError:
        checks.append(("Config file", False, "home dir not found"))

    # 4. Core imports
    core_modules = ["run_agent", "model_tools", "harness_constants", "harness_logging"]
    for mod in core_modules:
        try:
            __import__(mod)
            checks.append((f"Module: {mod}", True, "OK"))
        except ImportError as exc:
            checks.append((f"Module: {mod}", False, str(exc)))

    # 5. OpenAI SDK
    try:
        import openai
        checks.append(("OpenAI SDK", True, openai.__version__))
    except ImportError:
        checks.append(("OpenAI SDK", False, "not installed"))

    # 6. Optional providers
    for provider, pkg in [("Anthropic", "anthropic"), ("Google Gemini", "google.genai")]:
        try:
            __import__(pkg)
            checks.append((f"Provider: {provider}", True, "available"))
        except ImportError:
            checks.append((f"Provider: {provider}", False, "not installed (optional)"))

    # Print results
    print("harness_x doctor — Setup Diagnostics\n")
    all_ok = True
    for label, ok, detail in checks:
        status = "✓" if ok else "✗"
        print(f"  {status} {label}: {detail}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print("All checks passed.")
    else:
        print("Some checks failed. See above for details.")
        sys.exit(1)


def _print_help() -> None:
    """Print usage help."""
    print("""harness_x — Core AI Agent Framework

Usage:
    python -m harness_x                          Interactive chat
    python -m harness_x chat                     Interactive chat
    python -m harness_x chat -q "Hello"          One-shot query
    python -m harness_x doctor                   Diagnose setup issues
    python -m harness_x --version                Print version
    python -m harness_x help                     Show this help

Environment:
    HARNESS_HOME         Home directory (default: ~/.harness_x)
    HARNESS_API_KEY      Default API key for LLM provider
    HARNESS_BASE_URL     Default API base URL
    HARNESS_MODEL        Default model name
""")


def _print_version() -> None:
    """Print version information."""
    try:
        from importlib.metadata import version
        v = version("harness-x")
    except Exception:
        v = "0.1.0"
    print(f"harness_x {v}")


if __name__ == "__main__":
    main()
