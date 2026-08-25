"""Orrery Work's read layer: what the model can see of an attached folder, and what it cannot.

These tools cannot damage anything, which is exactly why they come before the ones that can — but
"read-only" is not the same as "harmless". A read tool that follows a symlink out of the root
exfiltrates whatever it lands on, and a grep that walks `node_modules` hangs the turn. Both are
pinned here.

Every path still goes through `resolve_in_root`; these tests check that it is actually reached, not
that it works — it has its own abuse suite in `test_workspace_confinement.py`.
"""
import pytest

from backend.features import workspace


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "project"
    (r / "src").mkdir(parents=True)
    (r / "src" / "main.py").write_text("import os\nprint('hello')\nprint('world')\n", encoding="utf-8")
    (r / "src" / "util.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (r / "README.md").write_text("# Project\nhello from the readme\n", encoding="utf-8")
    (r / "node_modules" / "left-pad").mkdir(parents=True)
    (r / "node_modules" / "left-pad" / "index.js").write_text("hello\n", encoding="utf-8")
    (r / ".git").mkdir()
    (r / ".git" / "config").write_text("hello\n", encoding="utf-8")
    outside = tmp_path / "secrets"
    outside.mkdir()
    (outside / "keys.txt").write_text("sk-do-not-read", encoding="utf-8")
    return r


# --- reading a file -------------------------------------------------------------------------------

def test_read_returns_the_file_with_its_path_relative_to_the_root(root):
    out = workspace.read_file(root, "src/main.py")
    assert out["path"] == "src/main.py"          # relative: absolute paths leak where the folder lives
    assert "print('hello')" in out["text"]
    assert out["truncated"] is False


def test_read_refuses_a_path_outside_the_root(root):
    with pytest.raises(workspace.PathOutsideRoot):
        workspace.read_file(root, "../secrets/keys.txt")


def test_read_of_a_missing_file_says_so_rather_than_returning_nothing(root):
    with pytest.raises(FileNotFoundError):
        workspace.read_file(root, "src/nope.py")


def test_read_of_a_directory_is_not_silently_empty(root):
    with pytest.raises(IsADirectoryError):
        workspace.read_file(root, "src")


def test_read_caps_a_large_file_and_says_that_it_did(root):
    (root / "big.txt").write_text("x" * 5000, encoding="utf-8")

    out = workspace.read_file(root, "big.txt", max_bytes=1000)

    assert len(out["text"]) <= 1000
    assert out["truncated"] is True             # silently returning a prefix is how a model concludes
    assert out["size"] == 5000                  # a file ends where it doesn't


def test_read_of_a_binary_file_refuses_instead_of_returning_mojibake(root):
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00")

    with pytest.raises(ValueError, match="binary"):
        workspace.read_file(root, "logo.png")


# --- finding files --------------------------------------------------------------------------------

def test_find_matches_inside_the_root_and_returns_relative_paths(root):
    assert workspace.find(root, "src/*.py")["paths"] == ["src/main.py", "src/util.py"]


def test_find_walks_subdirectories_when_asked(root):
    assert "src/main.py" in workspace.find(root, "**/*.py")["paths"]


def test_find_skips_the_directories_nobody_means_and_says_which(root):
    """`**/*` over `node_modules` is how a turn hangs. Skipping is right; skipping silently is not —
    a model that asked for every file and got a filtered list would conclude the files don't exist."""
    out = workspace.find(root, "**/*.js")

    assert out["paths"] == []
    assert "node_modules" in out["skipped"]


def test_find_can_be_told_to_look_in_a_skipped_directory(root):
    """The skip is a default, not a wall — a pattern that names the directory means it."""
    assert workspace.find(root, "node_modules/**/*.js")["paths"] == ["node_modules/left-pad/index.js"]


def test_find_refuses_a_pattern_that_climbs_out_of_the_root(root):
    with pytest.raises(workspace.PathOutsideRoot):
        workspace.find(root, "../secrets/*.txt")


def test_find_caps_its_results_and_says_that_it_did(root):
    for i in range(30):
        (root / "src" / f"gen{i}.py").write_text("x", encoding="utf-8")

    out = workspace.find(root, "src/*.py", limit=10)

    assert len(out["paths"]) == 10
    assert out["truncated"] is True


# --- searching contents ---------------------------------------------------------------------------

def test_grep_reports_the_file_the_line_number_and_the_line(root):
    hits = workspace.grep(root, "hello")["matches"]

    assert {"path": "README.md", "line": 2, "text": "hello from the readme"} in hits
    assert {"path": "src/main.py", "line": 2, "text": "print('hello')"} in hits


def test_grep_takes_a_regular_expression(root):
    assert workspace.grep(root, r"^def \w+\(")["matches"][0]["path"] == "src/util.py"


def test_grep_says_a_bad_expression_is_bad_instead_of_raising_at_the_caller(root):
    with pytest.raises(ValueError, match="expression"):
        workspace.grep(root, "unclosed (group")


def test_grep_can_be_narrowed_to_a_glob(root):
    hits = workspace.grep(root, "hello", glob="*.md")["matches"]

    assert [h["path"] for h in hits] == ["README.md"]


def test_grep_skips_the_heavy_directories_too(root):
    """`hello` is in node_modules and .git as well; neither should be walked by default."""
    paths = {h["path"] for h in workspace.grep(root, "hello")["matches"]}

    assert not any(p.startswith(("node_modules/", ".git/")) for p in paths)


def test_grep_skips_binary_files_rather_than_matching_bytes(root):
    (root / "blob.bin").write_bytes(b"\x00\x01hello\x00\x02")

    assert all(h["path"] != "blob.bin" for h in workspace.grep(root, "hello")["matches"])


def test_grep_truncates_a_very_long_line(root):
    (root / "min.js").write_text("hello" + "x" * 5000, encoding="utf-8")

    hit = next(h for h in workspace.grep(root, "hello", glob="*.js")["matches"])

    assert len(hit["text"]) <= workspace.MAX_LINE_CHARS


def test_grep_caps_its_matches_and_says_that_it_did(root):
    (root / "many.txt").write_text("hello\n" * 100, encoding="utf-8")

    out = workspace.grep(root, "hello", limit=5)

    assert len(out["matches"]) == 5
    assert out["truncated"] is True


def test_grep_refuses_a_glob_that_climbs_out_of_the_root(root):
    with pytest.raises(workspace.PathOutsideRoot):
        workspace.grep(root, "sk-", glob="../secrets/*.txt")


# --- bounds that have to hold on the way IN, not on the way out ------------------------------------

def test_read_never_pulls_a_huge_file_into_memory_to_throw_most_of_it_away(root, monkeypatch):
    """Capping the result after `read_bytes()` caps the output and not the cost — an attached folder
    with a multi-gigabyte log in it would take the process down before the slice ever ran."""
    read = {}
    target = root / "huge.log"
    target.write_text("y" * 50_000, encoding="utf-8")

    real_open = type(target).open

    def spy_open(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        if self.name == "huge.log":
            real_read = handle.read

            def bounded(*a):
                data = real_read(*a)
                read["bytes"] = max(read.get("bytes", 0), len(data))
                return data
            handle.read = bounded
        return handle

    monkeypatch.setattr(type(target), "open", spy_open)
    out = workspace.read_file(root, "huge.log", max_bytes=1000)

    assert out["truncated"] is True
    assert read["bytes"] <= 2000, "the whole file was read before being truncated"


def test_grep_does_not_read_an_enormous_file_to_search_it(root):
    """Same trap on the search path, where it applies to every file in the folder at once."""
    (root / "enormous.txt").write_text("z" * (workspace.MAX_GREP_FILE_BYTES + 5000), encoding="utf-8")

    out = workspace.grep(root, "z+")

    assert "enormous.txt" in out["skipped_files"]
    assert all(m["path"] != "enormous.txt" for m in out["matches"])
