"""Infer the file reads and writes of a recorded shell command.

A trajectory records the text of a shell command and its output, not what the
command did internally. This module recovers file operations from the command
text, using the rules named in docs/graph-format.md Section 4.1:

  command-text   the path appears in the command as something read or written
  known-script   declared behavior of a script in the workspace

It is a set of conservative heuristics, not a shell interpreter. It handles
the constructs that occur in the recorded runs: pipelines and command lists,
redirections, here-documents, cd, mv, cp, rm, tee, sed -i, and Python run as a
script, a module, inline code, or from standard input.

Known limits: variables, globs, subshells, and command substitution are not
expanded; a newline outside quotes is not treated as a command separator; and
paths computed at run time (for example temporary files) are not seen.
"""

from __future__ import annotations

import fnmatch
import hashlib
import posixpath
import re
import shlex
from dataclasses import dataclass, field

# Files a workspace script reads when it runs, declared from reading its source.
# tools/run_tests.py runs unittest discovery over tests/ (which imports src/)
# and then prints docs/runner-notes.txt.
KNOWN_SCRIPTS: dict[str, list[str]] = {
    "tools/run_tests.py": ["docs/runner-notes.txt", "tests/test*.py", "src/*.py"],
}

SEPARATORS = {"&&", "||", ";", "|", "|&", "&"}
# Programs whose path arguments are not read for content.
NO_CONTENT_READ = {
    "ls", "find", "mkdir", "rmdir", "echo", "printf", "test", "[", "stat", "pwd",
    "true", "false", "which", "export", "chmod", "cd", "touch", "rm", "mv", "cp", "tee",
}
PYTHON = re.compile(r"^python(\d(\.\d+)?)?$")
HEREDOC = re.compile(r"<<-?[ \t]*(['\"]?)(\w+)\1([^\n]*)\n(.*?)\n[ \t]*\2(?=\n|$)", re.S)
PLACEHOLDER = re.compile(r"^__HEREDOC_(\d+)__$")

IMPORT_FROM = re.compile(r"(?:^|[;\n])[ \t]*from[ \t]+([\w.]+)[ \t]+import")
IMPORT_PLAIN = re.compile(r"(?:^|[;\n])[ \t]*import[ \t]+([\w., \t]+)")
PY_WRITE_PATH = re.compile(r"Path\(\s*(['\"])([^'\"]+)\1\s*\)\s*\.\s*write_(?:text|bytes)\(")
PY_OPEN = re.compile(r"open\(\s*(['\"])([^'\"]+)\1\s*(?:,\s*(['\"])([A-Za-z+]+)\3)?")
PY_READ_PATH = re.compile(r"Path\(\s*(['\"])([^'\"]+)\1\s*\)\s*\.\s*read_(?:text|bytes)\(")


@dataclass
class FileOp:
    kind: str                    # "read", "write", or "delete"
    path: str                    # workspace-relative, or absolute if outside it
    rule: str                    # "command-text" or "known-script"
    append: bool = False         # a write that keeps the existing content
    copy_of: str | None = None   # a write whose content equals this path's
    sha256: str | None = None    # hash of the written content when it is literal


@dataclass
class Analysis:
    ops: list[FileOp] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    programs: list[str] = field(default_factory=list)


def resolve(path: str, cwd: str) -> str | None:
    """Normalize a path from a command; None for paths that are not files."""
    if not path or path.startswith("/dev/") or path == "-":
        return None
    joined = path if path.startswith("/") else posixpath.join(cwd, path)
    return posixpath.normpath(joined)


def _module_files(module: str) -> list[str]:
    """Files Python may load to import a dotted module name."""
    parts = module.strip().split(".")
    files = [posixpath.join(*parts[:i], "__init__.py") for i in range(1, len(parts) + 1)]
    files.append(posixpath.join(*parts) + ".py")
    return files


class _Analyzer:
    def __init__(self, existing: set[str], exit_code: int | None):
        self.existing = set(existing)
        self.exit_code = exit_code
        self.cwd = "."
        self.result = Analysis()
        self.heredocs: list[tuple[bool, str]] = []   # (delimiter quoted, body)

    # -- recording -----------------------------------------------------------

    def read(self, path: str | None, rule: str = "command-text") -> None:
        if path and path in self.existing:
            self.result.ops.append(FileOp("read", path, rule))

    def write(self, path: str | None, *, append: bool = False, copy_of: str | None = None,
              sha256: str | None = None) -> None:
        if path:
            self.result.ops.append(FileOp("write", path, "command-text", append=append,
                                          copy_of=copy_of, sha256=sha256))
            self.existing.add(path)

    def delete(self, path: str | None) -> None:
        if path and path in self.existing:
            self.result.ops.append(FileOp("delete", path, "command-text"))
            self.existing.discard(path)

    # -- parsing -------------------------------------------------------------

    def run(self, command: str) -> Analysis:
        def stash(match: re.Match) -> str:
            self.heredocs.append((bool(match.group(1)), match.group(4)))
            return f" __HEREDOC_{len(self.heredocs) - 1}__ {match.group(3)}"

        text = HEREDOC.sub(stash, command)
        try:
            lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError as error:
            self.result.notes.append(f"command could not be tokenized ({error}); no file operations inferred")
            return self.result

        simple: list[str] = []
        for token in tokens + [";"]:
            if token in SEPARATORS:
                if simple:
                    self.simple_command(simple)
                simple = []
            else:
                simple.append(token)
        return self.result

    def simple_command(self, tokens: list[str]) -> None:
        if any(token and set(token) <= set("()") for token in tokens):
            # Subshells, function definitions, or text that is not valid shell.
            self.result.notes.append("part of the command uses parentheses, which are not analyzed")
            return
        words: list[str] = []
        bodies: list[tuple[bool, str]] = []
        outputs: list[tuple[str, bool]] = []
        inputs: list[str] = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            following = tokens[i + 1] if i + 1 < len(tokens) else None
            if token in (">", ">>", ">|", "&>", "&>>"):
                if words and words[-1].isdigit():
                    words.pop()                      # file descriptor, as in 2>
                if following is not None:
                    outputs.append((following, token.endswith(">>")))
                i += 2
            elif token in (">&", "<&"):
                if words and words[-1].isdigit():
                    words.pop()
                if token == ">&" and following and not following.isdigit() and following != "-":
                    outputs.append((following, False))
                i += 2
            elif token == "<":
                if following is not None:
                    inputs.append(following)
                i += 2
            elif token == "<<<":
                i += 2                               # here-string: literal input
            elif PLACEHOLDER.match(token):
                bodies.append(self.heredocs[int(PLACEHOLDER.match(token).group(1))])
                i += 1
            else:
                words.append(token)
                i += 1

        while words and re.match(r"^[A-Za-z_]\w*=", words[0]):
            words.pop(0)                             # VAR=value prefix
        program = posixpath.basename(words[0]) if words else ""
        args = words[1:]
        if program:
            self.result.programs.append(program)

        for path in inputs:
            self.read(resolve(path, self.cwd))
        self.program(program, args, bodies)

        # A redirection takes effect even when the command itself fails.
        for target, append in outputs:
            sha256 = None
            if program == "cat" and not args and len(bodies) == 1 and len(outputs) == 1 and not append:
                quoted, body = bodies[0]
                if quoted or not re.search(r"[$`\\]", body):
                    sha256 = hashlib.sha256((body + "\n").encode("utf-8")).hexdigest()
            self.write(resolve(target, self.cwd), append=append, sha256=sha256)

    def program(self, program: str, args: list[str], bodies: list[tuple[bool, str]]) -> None:
        plain = [arg for arg in args if not arg.startswith("-")]
        paths = [resolve(arg, self.cwd) for arg in plain]

        if program == "cd":
            if plain:
                self.cwd = resolve(plain[0], self.cwd) or self.cwd
        elif program in ("mv", "cp"):
            if len(paths) >= 2 and paths[-1]:
                for source in paths[:-1]:
                    if source in self.existing:
                        self.read(source)
                        self.write(paths[-1], copy_of=source)
                        if program == "mv":
                            self.delete(source)
        elif program == "rm":
            for path in paths:
                self.delete(path)
        elif program == "tee":
            for path in paths:
                self.write(path, append="-a" in args or "--append" in args)
        elif program == "touch":
            for path in paths:
                if path and path not in self.existing:
                    self.write(path, sha256=hashlib.sha256(b"").hexdigest())
        elif program == "sed" and any(arg == "-i" or arg.startswith("-i") for arg in args):
            for path in paths:
                if path in self.existing:
                    self.read(path)
                    self.write(path)
        elif PYTHON.match(program):
            self.python(args, bodies)
        elif program and program not in NO_CONTENT_READ:
            for path in paths:
                self.read(path)

    def python(self, args: list[str], bodies: list[tuple[bool, str]]) -> None:
        code: list[str] = [body for _, body in bodies]
        rest: list[str] = []
        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "-c" and i + 1 < len(args):
                code.append(args[i + 1])
                rest = args[i + 2:]
                break
            if arg == "-m" and i + 1 < len(args):
                for path in _module_files(args[i + 1]):
                    self.read(resolve(path, self.cwd))
                rest = args[i + 2:]
                break
            if not arg.startswith("-"):
                script = resolve(arg, self.cwd)
                self.read(script)
                for pattern in KNOWN_SCRIPTS.get(script or "", []):
                    for path in sorted(fnmatch.filter(self.existing, pattern)):
                        self.read(path, rule="known-script")
                rest = args[i + 1:]
                break
            i += 1
        for arg in rest:
            if not arg.startswith("-"):
                self.read(resolve(arg, self.cwd))
        for source in code:
            self.python_code(source)

    def python_code(self, code: str) -> None:
        modules = IMPORT_FROM.findall(code)
        for group in IMPORT_PLAIN.findall(code):
            modules.extend(name.split()[0] for name in group.split(",") if name.strip())
        for module in modules:
            for path in _module_files(module):
                self.read(resolve(path, self.cwd))
        for match in PY_READ_PATH.finditer(code):
            self.read(resolve(match.group(2), self.cwd))

        writes: list[tuple[str, bool]] = [(m.group(2), False) for m in PY_WRITE_PATH.finditer(code)]
        for match in PY_OPEN.finditer(code):
            mode = match.group(4) or "r"
            if any(flag in mode for flag in "wax"):
                writes.append((match.group(2), "a" in mode))
            else:
                self.read(resolve(match.group(2), self.cwd))
        for target, append in writes:
            path = resolve(target, self.cwd)
            # A failed interpreter may have stopped before the write, or never
            # started (a syntax error), so nothing is inferred from it.
            if self.exit_code == 0:
                self.write(path, append=append)
            elif path:
                self.result.notes.append(
                    f"Python code names {path} as a write target, but the command exited "
                    f"with status {self.exit_code}; no write inferred")


def analyze_command(command: str, existing: set[str], exit_code: int | None) -> Analysis:
    """Infer the file operations of one shell command.

    existing is the set of file paths that exist when the command starts. Reads
    are reported only for files in that set or created earlier in the command.
    """
    return _Analyzer(existing, exit_code).run(command)


def grep_output_paths(output: str) -> list[str]:
    """Paths that grep printed as `path:matching line`, in order of appearance."""
    paths: list[str] = []
    for line in output.splitlines():
        match = re.match(r"^([^\s:][^:\n]*):", line)
        if match and match.group(1) not in paths:
            paths.append(match.group(1))
    return paths
