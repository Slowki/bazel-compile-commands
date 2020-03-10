#!/usr/bin/env python3
"""Generate a compile_commands.json file for the workspace.

Usage: generate-compile-commands [targets...]
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path, PurePath
from typing import List

#: See https://docs.bazel.build/versions/master/user-manual.html#run
WORKSPACE_ENV_VARIABLE = "BUILD_WORKSPACE_DIRECTORY"

#: See https://clang.llvm.org/docs/JSONCompilationDatabase.html
COMPILE_COMMANDS = "compile_commands.json"

INCLUDE_FLAGS = frozenset({"-I", "-iquote", "-isystem"})


def find_workspace() -> Path:
    """Find the root of the current Bazel workspace."""
    # Try to get the workspace from Bazel itself if this script was run with `bazel run`
    if WORKSPACE_ENV_VARIABLE in os.environ:
        return Path(os.environ[WORKSPACE_ENV_VARIABLE])

    # Search for a WORKSPACE file
    directories = [Path.cwd()] + list(Path.cwd().parents)
    for directory in directories:
        if (directory / "WORKSPACE").exists():
            return directory

    # Fall back to using the root of the git repo if available.
    try:
        git_result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        return Path(git_result.stdout.strip())
    except subprocess.CalledProcessError:
        pass

    # 🤷
    return Path.cwd()


def process_action(action: dict, workspace: PurePath) -> dict:
    """Process an individual action into a compilation database entry."""
    output = None
    source = None
    arguments = action["arguments"]
    processed_arguments = list(arguments)

    # Try to find the main source file and output of the given translation unit.
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "-c":
            source = arguments[index + 1]
            index += 1
        elif argument == "-o":
            output = arguments[index + 1]
            index += 1
        index += 1

    # Rewrite the include paths so that external points to bazel-out/external
    is_include = False
    for i, argument in enumerate(arguments):
        if is_include:
            is_include = False
            if argument.startswith("external/"):
                processed_arguments[i] = f"bazel-out/{argument}"
        else:
            is_include = argument in INCLUDE_FLAGS

    assert output is not None, "Failed out detect action output"
    assert source is not None, "Failed out detect action input"

    return {
        "directory": str(workspace),
        "file": source,
        "arguments": list(processed_arguments),
        "output": output,
    }


def main(argv: List[str]):
    """The main CLI entrypoint."""
    workspace = find_workspace()
    targets = " ".join(argv) if argv else "//..."
    result = subprocess.run(
        [
            os.environ.get("BAZEL_REAL", "bazel"),
            "aquery",
            "--output=jsonproto",
            "--include_commandline",
            f"mnemonic(CppCompile, set({targets}))",
        ],
        cwd=workspace,
        stdout=subprocess.PIPE,
        universal_newlines=True,
    )
    if result.returncode != 0:
        sys.exit(result.returncode)

    action_graph = json.loads(result.stdout)

    entries = [process_action(action, workspace) for action in action_graph["actions"]]

    with (workspace / COMPILE_COMMANDS).open("w") as compile_commands_file:
        json.dump(entries, compile_commands_file, indent=4)


if __name__ == "__main__":
    main(sys.argv[1:])
