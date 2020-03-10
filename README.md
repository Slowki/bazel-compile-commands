# `generate-compile-commands`
Generate [`compile_commands.json`](https://clang.llvm.org/docs/JSONCompilationDatabase.html) files from [Bazel](https://bazel.build/)'s action graph.

## Usage with Bazel
```sh
$ bazel run @generate_compile_commands//:generate_compile_commands
# or
$ bazel run @generate_compile_commands//:generate_compile_commands -- //path/to/package/... //other/package/...
```

### Example `http_archive`
```py
load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

VERSION = "<COMMIT-HASH>"
http_archive(
    name = "generate_compile_commands",
    urls = ["https://github.com/Slowki/bazel-compile-commands/archive/{}.tar.gz".format(VERSION)],
    strip_prefix = "generate_compile_commands-" + VERSION,
    sha256 = "<SHA256>",
)
```

## Standalone Usage
```sh
$ generate-compile-commands
# or
$ generate-compile-commands //path/to/package/... //other/package/...
```
