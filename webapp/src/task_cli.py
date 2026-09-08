#!/usr/bin/env python3
"""
Task State CLI for OpenCode Persistent Task System

This module provides a CLI entry point for the task state management system,
accessible as 'task-state' command after installation.
"""

import sys
import os
from pathlib import Path

# Add project root to path to import task_state
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / ".opencode"))

from task_state import TaskStateManager, main as task_state_main


def main():
    """Entry point for the task-state command."""
    # Change to project root so task state manager finds .opencode directory
    os.chdir(project_root)
    task_state_main()


if __name__ == "__main__":
    main()