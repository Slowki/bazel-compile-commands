#!/usr/bin/env python3
"""Generate a compile_commands.json file for the workspace.

Usage: generate-compile-commands [bazel_flags] [targets...]
"""

import itertools
import json
import os
import subprocess
import sys
from pathlib import Path, PurePath
from typing import List

#: See https://docs.bazel.build/versions/master/user-manual.html#run
WORKSPACE_ENV_VARIABLE = "BUILD_WORKSPACE_DIRECTORY"

#: See https://clang.llvm.org/docs/JSONCompilationDatabase.html
COMPILE_COMMANDS = "compile_commands.json"

TEMPLATE_EXTENSIONS = [".inl", ".tcc"]
HEADER_EXTENSIONS = [".hh", ".hpp", ".h"]

INCLUDE_FLAG = frozenset({"-I", "-iquote", "-isystem"})

BAZEL = os.environ.get("BAZEL_REAL", "bazel")


def bazel_info(key: str) -> str:
    bazel_result = subprocess.run(
        [BAZEL, "info", key], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )
    return bazel_result.stdout.strip()


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

    # Fall back to using a subprocess
    try:
        return Path(bazel_info("workspace"))
    except subprocess.CalledProcessError:
        pass

    # 🤷
    return Path.cwd()


def rewrite_include(include: str, execroot_external: str, output_base: PurePath) -> str:
    EXTERNAL = "external/"

    if include.startswith(execroot_external):
        return os.fspath(output_base / "external" / include[len(execroot_external) :])
    if include.startswith(EXTERNAL):
        return os.fspath(output_base / "external" / include[len(EXTERNAL) :])
    return include


def process_action(action: dict, workspace: PurePath, output_base: PurePath) -> dict:
    """Process an individual action into a compilation database entry."""
    execroot = workspace / f"bazel-{workspace.name}"
    execroot_external = os.fspath(execroot / "external")
    output = None
    source = None
    arguments = action["arguments"]
    include_directories = []

    # Try to find the main source file and output of the given translation unit.
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "-c":
            source = arguments[index + 1]
            arguments[index + 1] = os.fspath(workspace / source)
            index += 1
        elif argument == "-o":
            output = arguments[index + 1]
            index += 1
        elif argument in INCLUDE_FLAG:
            arguments[index + 1] = rewrite_include(arguments[index + 1], execroot_external, output_base)
            include_directories.append((argument, arguments[index + 1]))
            index += 1
        else:
            include = next(((flag, argument[len(flag) :]) for flag in INCLUDE_FLAG if argument.startswith(flag)), None)
            if include:
                arguments[index] = include[0] + rewrite_include(include[1], execroot_external, output_base)
                include_directories.append(include)

        index += 1

    assert output is not None, "Failed out detect action output"
    assert source is not None, "Failed out detect action input"

    for flag, include_dir in include_directories:
        # Look in both the workspace and the exec root for non-external and non-generated headers.
        if include_dir[0] != "/" and not include_dir.startswith("bazel-") and not include_dir.startswith("external/"):
            arguments.extend((flag, os.fspath(workspace / include_dir)))

    source_file = workspace / source
    if not source_file.exists():
        source_file = execroot / source

    return {
        "directory": os.fspath(execroot),
        "file": os.fspath(source_file),
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
        [BAZEL, "aquery", "--output=jsonproto", "--include_commandline"] + flags,
        cwd=workspace,
        stdout=subprocess.PIPE,
        universal_newlines=True,
    )
    if result.returncode != 0:
        sys.exit(result.returncode)

    action_graph = json.loads(result.stdout)

    output_base = Path(bazel_info("output_base"))
    entries = [process_action(action, workspace, output_base) for action in action_graph.get("actions", [])]
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
