#!/usr/bin/env python3
"""Generate a compile_commands.json file for the workspace.

Usage: generate-compile-commands [bazel_flags] [targets...]
"""

import itertools
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

TEMPLATE_EXTENSIONS = [".inl", ".tcc"]
HEADER_EXTENSIONS = [".hh", ".hpp", ".h"]


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

    assert output is not None, "Failed out detect action output"
    assert source is not None, "Failed out detect action input"

    return {
        "directory": str(workspace / f"bazel-{workspace.name}"),
        "file": str(workspace / source),
        "arguments": list(arguments),
        "output": output,
    }


def main(argv: List[str]):
    """The main CLI entrypoint."""
    workspace = find_workspace()
    flags = list(itertools.takewhile(lambda x: x.startswith("-"), argv))
    targets = argv[len(flags) :] if len(argv) > len(flags) else ["//..."]
    subtracted_targets = " ".join(target[1:] for target in targets if target.startswith("-"))
    selected_targets = " ".join((target for target in targets if not target.startswith("-")))

    flags.append(f"mnemonic(CppCompile, set({selected_targets}) - set({subtracted_targets}))")
    result = subprocess.run(
        [os.environ.get("BAZEL_REAL", "bazel"), "aquery", "--output=jsonproto", "--include_commandline"] + flags,
        cwd=workspace,
        stdout=subprocess.PIPE,
        universal_newlines=True,
    )
    if result.returncode != 0:
        sys.exit(result.returncode)

    action_graph = json.loads(result.stdout)

    entries = [process_action(action, workspace) for action in action_graph.get("actions", [])]
    entries_by_filename = {Path(entry["file"]): entry for entry in entries}

    # Add entries for template implementation files
    for file_path, entry in entries_by_filename.items():
        for inl_extension in TEMPLATE_EXTENSIONS:
            inl_file = file_path.with_suffix(inl_extension)
            if (workspace / inl_file).exists() and inl_file not in entries_by_filename:
                inl_entry = dict(entry)
                inl_entry["file"] = str(inl_file)
                del inl_entry["output"]
                for header_extension in HEADER_EXTENSIONS:
                    header_file = inl_file.with_suffix(header_extension)
                    if (workspace / header_file).exists():
                        inl_entry["arguments"].extend(["-include", str(header_file)])
                        break
                entries.append(inl_entry)

    with (workspace / COMPILE_COMMANDS).open("w") as compile_commands_file:
        json.dump(entries, compile_commands_file, indent=4)


if __name__ == "__main__":
    main(sys.argv[1:])
