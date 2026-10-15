#!/usr/bin/env python3
"""Decide whether a directory is a plugin marketplace repository.

Usage: python3 is_marketplace_repo.py [<dir>]

Exits 0 and prints nothing when <dir> is a marketplace repository: it holds
.claude-plugin/marketplace.json, and `git rev-parse --show-toplevel`, run in
<dir>, resolves to <dir> itself (both as real paths). Exits 1 and prints
nothing otherwise. A marketplace.json in a subdirectory, in a submodule, or in
a directory that is not a git repository does not qualify.

With no argument, <dir> is the CLAUDE_PROJECT_DIR environment variable, else
the current directory.
"""
import os
import subprocess
import sys

MANIFEST = os.path.join(".claude-plugin", "marketplace.json")

# Variables that a parent process, such as a git hook, may set. They would
# point the probe at a different repository, so the probe drops them.
GIT_ENV_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


def git_toplevel(directory):
    env = {k: v for k, v in os.environ.items() if k not in GIT_ENV_VARS}
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=directory,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    top = result.stdout.strip()
    if result.returncode != 0 or not top:
        return None
    return os.path.realpath(top)


def is_marketplace_repo(directory):
    real = os.path.realpath(directory)
    if not os.path.isfile(os.path.join(real, MANIFEST)):
        return False
    return git_toplevel(real) == real


def main(argv):
    if len(argv) > 2:
        return 1
    if len(argv) == 2:
        directory = argv[1]
    else:
        directory = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    # An empty argument means a placeholder expanded to nothing; it is not
    # a directory, so it never qualifies.
    if directory == "":
        return 1
    return 0 if is_marketplace_repo(directory) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
