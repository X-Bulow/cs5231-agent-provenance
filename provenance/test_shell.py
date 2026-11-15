"""Checks of the shell command analysis.

Run from the repository root:
    python3 -m unittest discover -s provenance -v
"""

import hashlib
import unittest

from shell import analyze_command, grep_output_paths

FILES = {
    "data/expenses.csv", "docs/project-notes.md", "docs/runner-notes.txt",
    "src/__init__.py", "src/expense_summary.py",
    "tests/test_expense_summary.py", "tools/run_tests.py",
}


def ops(command, exit_code=0, files=FILES):
    return [(op.kind, op.path, op.rule) for op in analyze_command(command, set(files), exit_code).ops]


class Reads(unittest.TestCase):
    def test_cat_reads_and_ignores_dev_null(self):
        self.assertEqual(ops('cat data/expenses.csv 2>/dev/null || echo "File not found"'),
                         [("read", "data/expenses.csv", "command-text")])

    def test_pipeline_reads_the_first_file_only(self):
        self.assertEqual(ops("head -30 tests/test_expense_summary.py | tail -7"),
                         [("read", "tests/test_expense_summary.py", "command-text")])

    def test_listing_a_file_is_not_a_read(self):
        self.assertEqual(ops("ls -la data/expenses.csv 2>&1"), [])
        self.assertEqual(ops('find . -name "*.py" | grep -v __pycache__ | sort'), [])

    def test_unknown_files_are_not_reported(self):
        self.assertEqual(ops("python3 src/expenses_summary.py data/expenses.csv"),
                         [("read", "data/expenses.csv", "command-text")])

    def test_cd_changes_how_paths_resolve(self):
        self.assertEqual(ops("cd src && cat expense_summary.py"),
                         [("read", "src/expense_summary.py", "command-text")])
        self.assertEqual(ops("cd . && cat docs/project-notes.md"),
                         [("read", "docs/project-notes.md", "command-text")])

    def test_test_runner_uses_declared_reads(self):
        self.assertEqual(ops("python3 tools/run_tests.py 2>&1 | head -100"), [
            ("read", "tools/run_tests.py", "command-text"),
            ("read", "docs/runner-notes.txt", "known-script"),
            ("read", "tests/test_expense_summary.py", "known-script"),
            ("read", "src/__init__.py", "known-script"),
            ("read", "src/expense_summary.py", "known-script"),
        ])

    def test_python_module_and_script(self):
        self.assertEqual(ops("python3 -m src.expense_summary data/expenses.csv"), [
            ("read", "src/__init__.py", "command-text"),
            ("read", "src/expense_summary.py", "command-text"),
            ("read", "data/expenses.csv", "command-text"),
        ])
        self.assertEqual(ops("python3 src/expense_summary.py data/expenses.csv"), [
            ("read", "src/expense_summary.py", "command-text"),
            ("read", "data/expenses.csv", "command-text"),
        ])

    def test_python_inline_imports(self):
        command = 'python3 -c "from src.expense_summary import summarize; import json, sys; print(1)"'
        self.assertEqual(ops(command), [
            ("read", "src/__init__.py", "command-text"),
            ("read", "src/expense_summary.py", "command-text"),
        ])


class Writes(unittest.TestCase):
    def test_tee_and_redirection(self):
        result = ops("python3 tools/run_tests.py 2>&1 | tee outputs/before.txt")
        self.assertEqual(result[-1], ("write", "outputs/before.txt", "command-text"))
        self.assertEqual(ops("echo done > outputs/log.txt"),
                         [("write", "outputs/log.txt", "command-text")])

    def test_append_is_marked(self):
        analysis = analyze_command("echo more >> outputs/log.txt", set(FILES), 0)
        self.assertEqual([(op.kind, op.path, op.append) for op in analysis.ops],
                         [("write", "outputs/log.txt", True)])

    def test_move_reads_writes_and_deletes(self):
        files = FILES | {"tests/test_expense_summary.py.fixed"}
        command = ("cd . && mv tests/test_expense_summary.py.fixed tests/test_expense_summary.py"
                   " && python3 tools/run_tests.py 2>&1 | tail -8")
        analysis = analyze_command(command, set(files), 0)
        first = [(op.kind, op.path, op.copy_of) for op in analysis.ops[:3]]
        self.assertEqual(first, [
            ("read", "tests/test_expense_summary.py.fixed", None),
            ("write", "tests/test_expense_summary.py", "tests/test_expense_summary.py.fixed"),
            ("delete", "tests/test_expense_summary.py.fixed", None),
        ])

    def test_copy_and_remove(self):
        self.assertEqual(ops("cp data/expenses.csv outputs/copy.csv"), [
            ("read", "data/expenses.csv", "command-text"),
            ("write", "outputs/copy.csv", "command-text"),
        ])
        self.assertEqual(ops("rm -f data/expenses.csv missing.txt"),
                         [("delete", "data/expenses.csv", "command-text")])

    def test_heredoc_write_has_a_content_hash(self):
        command = "mkdir -p outputs && cat > outputs/report.md << 'EOF'\n# Report\nline two\nEOF"
        analysis = analyze_command(command, set(FILES), 0)
        self.assertEqual([(op.kind, op.path) for op in analysis.ops], [("write", "outputs/report.md")])
        self.assertEqual(analysis.ops[0].sha256,
                         hashlib.sha256(b"# Report\nline two\n").hexdigest())

    def test_python_literal_write_needs_a_clean_exit(self):
        command = "python3 -c \"f = open('/tmp/test.csv', 'w'); f.write('x'); f.close()\""
        self.assertEqual(ops(command, exit_code=0), [("write", "/tmp/test.csv", "command-text")])
        failed = analyze_command(command, set(FILES), 1)
        self.assertEqual(failed.ops, [])
        self.assertEqual(len(failed.notes), 1)

    def test_python_heredoc_write(self):
        command = ("python3 << 'EOF'\nfrom pathlib import Path\n"
                   "Path('tests/test_expense_summary.py').write_text('x')\nEOF")
        self.assertEqual(ops(command, exit_code=0),
                         [("write", "tests/test_expense_summary.py", "command-text")])
        self.assertEqual(ops(command, exit_code=1), [])


class Other(unittest.TestCase):
    def test_text_that_is_not_shell_is_skipped(self):
        analysis = analyze_command("cat data/expenses.csv; summarize(Path('/tmp/x'))", set(FILES), 1)
        self.assertEqual([(op.kind, op.path) for op in analysis.ops], [("read", "data/expenses.csv")])
        self.assertEqual(len(analysis.notes), 1)

    def test_unbalanced_quotes_do_not_raise(self):
        analysis = analyze_command("echo 'unterminated", set(FILES), 2)
        self.assertEqual(analysis.ops, [])
        self.assertEqual(len(analysis.notes), 1)

    def test_grep_output_paths(self):
        output = 'src/expense_summary.py:    if kind not in {"charge", "refund"}:\nno match here\n'
        self.assertEqual(grep_output_paths(output), ["src/expense_summary.py"])


if __name__ == "__main__":
    unittest.main()
