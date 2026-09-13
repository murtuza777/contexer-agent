"""Unit tests for workspace-sandboxed filesystem tools."""

from pathlib import Path

import pytest

from contexer.tools.filesystem import (
    MAX_FILE_SIZE_BYTES,
    file_exists,
    list_directory,
    read_file,
    search_files,
    write_file,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace with representative files."""
    ws = tmp_path / "test_workspace"
    ws.mkdir()

    # Create subdirectories and files
    src_dir = ws / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("def main():\n    print('hello world')\n", encoding="utf-8")
    (src_dir / "utils.py").write_text("# utility functions\nFOO = 'bar'\n", encoding="utf-8")

    (ws / "README.md").write_text("# Test Project\nA demo project for testing.", encoding="utf-8")
    (ws / ".env").write_text("SECRET_KEY=super_secret\n", encoding="utf-8")
    return ws


class TestListDirectory:
    """list_directory operations and boundary enforcement."""

    def test_list_root(self, workspace: Path) -> None:
        result = list_directory(workspace, ".")
        assert "Contents of '.':" in result
        assert "[DIR]  src/" in result
        assert "[FILE] README.md" in result
        # .env should not be visible or accessible
        assert ".env" not in result

    def test_list_subdirectory(self, workspace: Path) -> None:
        result = list_directory(workspace, "src")
        assert "Contents of 'src':" in result
        assert "[FILE] main.py" in result
        assert "[FILE] utils.py" in result

    def test_list_nonexistent_directory(self, workspace: Path) -> None:
        result = list_directory(workspace, "nonexistent")
        assert "Error: Directory 'nonexistent' does not exist." in result

    def test_list_file_as_directory(self, workspace: Path) -> None:
        result = list_directory(workspace, "README.md")
        assert "is a file, not a directory" in result

    def test_list_directory_traversal_blocked(self, workspace: Path) -> None:
        result = list_directory(workspace, "../../")
        assert "Access denied" in result
        assert "resolves outside the workspace" in result


class TestReadFile:
    """read_file operations, offsets, limits, and security."""

    def test_read_file_success(self, workspace: Path) -> None:
        result = read_file(workspace, "README.md")
        assert "1 | # Test Project" in result
        assert "2 | A demo project for testing." in result

    def test_read_file_offset_and_limit(self, workspace: Path) -> None:
        result = read_file(workspace, "README.md", offset=1, limit=1)
        assert "2 | A demo project for testing." in result
        assert "1 | # Test Project" not in result

    def test_read_file_offset_beyond_eof(self, workspace: Path) -> None:
        result = read_file(workspace, "README.md", offset=100)
        assert "beyond end of file" in result

    def test_read_file_nonexistent(self, workspace: Path) -> None:
        result = read_file(workspace, "missing.txt")
        assert "Error: File 'missing.txt' does not exist." in result

    def test_read_directory_as_file(self, workspace: Path) -> None:
        result = read_file(workspace, "src")
        assert "is a directory, not a file" in result

    def test_read_env_file_blocked(self, workspace: Path) -> None:
        result = read_file(workspace, ".env")
        assert "Access denied" in result
        assert ".env" in result

    def test_read_path_traversal_blocked(self, workspace: Path) -> None:
        result = read_file(workspace, "../outside.txt")
        assert "Access denied" in result
        assert "outside the workspace root" in result

    def test_read_oversized_file_blocked(self, workspace: Path) -> None:
        oversized = workspace / "huge.txt"
        # Write 150KB (limit is 100KB)
        oversized.write_text("x" * (MAX_FILE_SIZE_BYTES + 1024), encoding="utf-8")
        result = read_file(workspace, "huge.txt")
        assert "exceeds maximum allowable size" in result

    def test_read_binary_file_blocked(self, workspace: Path) -> None:
        binary_file = workspace / "binary.bin"
        binary_file.write_bytes(b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00")
        result = read_file(workspace, "binary.bin")
        assert "file appears to be binary" in result

    def test_read_oversized_file_chunked_success(self, workspace: Path) -> None:
        oversized = workspace / "huge_lines.txt"
        oversized.write_text("\n".join(f"line_{i}" for i in range(10000)), encoding="utf-8")
        result = read_file(workspace, "huge_lines.txt", offset=10, limit=5)
        assert "11 | line_10" in result
        assert "15 | line_14" in result

    def test_symlink_escape_blocked(self, workspace: Path, tmp_path: Path) -> None:
        outside_file = tmp_path / "outside_secret.txt"
        outside_file.write_text("SUPER_SECRET", encoding="utf-8")
        symlink = workspace / "link_outside"
        try:
            symlink.symlink_to(outside_file)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks not supported on this platform/privilege level")
        result = read_file(workspace, "link_outside")
        assert "Access denied" in result


class TestWriteFile:
    """write_file operations, directory creation, and restrictions."""

    def test_write_new_file(self, workspace: Path) -> None:
        result = write_file(workspace, "new_file.txt", "Hello world")
        assert "Successfully wrote 11 characters to 'new_file.txt'" in result
        assert (workspace / "new_file.txt").read_text(encoding="utf-8") == "Hello world"

    def test_write_creates_intermediate_directories(self, workspace: Path) -> None:
        result = write_file(workspace, "a/b/c/nested.txt", "nested content")
        assert "Successfully wrote" in result
        assert (workspace / "a" / "b" / "c" / "nested.txt").read_text(encoding="utf-8") == "nested content"

    def test_write_overwrite_existing_file(self, workspace: Path) -> None:
        write_file(workspace, "file.txt", "v1")
        result = write_file(workspace, "file.txt", "v2")
        assert "Successfully wrote 2 characters" in result
        assert (workspace / "file.txt").read_text(encoding="utf-8") == "v2"

    def test_write_env_file_blocked(self, workspace: Path) -> None:
        result = write_file(workspace, ".env", "NEW_KEY=val")
        assert "Access denied" in result

    def test_write_path_traversal_blocked(self, workspace: Path) -> None:
        result = write_file(workspace, "../../escaped.txt", "malicious")
        assert "Access denied" in result
        assert not (workspace.parent / "escaped.txt").exists()


class TestFileExists:
    """file_exists query tool."""

    def test_file_exists_on_file(self, workspace: Path) -> None:
        result = file_exists(workspace, "README.md")
        assert "File exists: 'README.md'" in result

    def test_file_exists_on_directory(self, workspace: Path) -> None:
        result = file_exists(workspace, "src")
        assert "Directory exists: 'src'" in result

    def test_file_exists_on_missing(self, workspace: Path) -> None:
        result = file_exists(workspace, "missing.py")
        assert "Path 'missing.py' does not exist." in result

    def test_file_exists_traversal_blocked(self, workspace: Path) -> None:
        result = file_exists(workspace, "../something")
        assert "Access denied" in result


class TestSearchFiles:
    """search_files keyword and regex searching."""

    def test_search_pattern_found(self, workspace: Path) -> None:
        result = search_files(workspace, "hello world")
        assert "main.py:2" in result
        assert "hello world" in result

    def test_search_pattern_not_found(self, workspace: Path) -> None:
        result = search_files(workspace, "nonexistent_pattern_xyz")
        assert "No matches found" in result

    def test_search_scoped_to_subdirectory(self, workspace: Path) -> None:
        result = search_files(workspace, "FOO", path="src")
        assert "utils.py" in result

    def test_search_traversal_blocked(self, workspace: Path) -> None:
        result = search_files(workspace, "secret", path="../../")
        assert "Access denied" in result
