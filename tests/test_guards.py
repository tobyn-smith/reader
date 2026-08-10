"""the guards around publishing: the commit hook, offline builds, print pdfs."""

import json
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

from vault import publish
from vault.site.build import build

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / ".githooks" / "pre-commit"

BASH = shutil.which("bash") or shutil.which("sh")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )


@pytest.mark.skipif(BASH is None, reason="no posix shell to run the hook")
class TestPreCommitHook:
    def _repo_with_hook(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@example.com")
        _git(repo, "config", "user.name", "t")
        hooks = repo / ".githooks"
        hooks.mkdir()
        shutil.copy(HOOK, hooks / "pre-commit")
        _git(repo, "config", "core.hooksPath", ".githooks")
        return repo

    def _hook_result(self, repo: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [BASH, str(repo / ".githooks" / "pre-commit")],
            cwd=repo, capture_output=True, text=True, check=False,
        )

    def test_staged_pdf_is_rejected(self, tmp_path):
        repo = self._repo_with_hook(tmp_path)
        (repo / "reading.pdf").write_bytes(b"%PDF-1.4 fake")
        _git(repo, "add", "reading.pdf")
        result = self._hook_result(repo)
        assert result.returncode != 0
        assert "reading.pdf" in result.stderr

    def test_staged_database_is_rejected(self, tmp_path):
        repo = self._repo_with_hook(tmp_path)
        (repo / "vault.sqlite").write_bytes(b"SQLite format 3\x00")
        _git(repo, "add", "vault.sqlite")
        result = self._hook_result(repo)
        assert result.returncode != 0
        assert "vault.sqlite" in result.stderr

    def test_ordinary_files_pass(self, tmp_path):
        repo = self._repo_with_hook(tmp_path)
        (repo / "notes.md").write_text("plain text", encoding="utf-8")
        _git(repo, "add", "notes.md")
        assert self._hook_result(repo).returncode == 0

    def test_fixture_pdfs_are_exempt(self, tmp_path):
        repo = self._repo_with_hook(tmp_path)
        target = repo / "tests" / "fixtures" / "syllabi"
        target.mkdir(parents=True)
        (target / "sample.pdf").write_bytes(b"%PDF-1.4 fixture")
        _git(repo, "add", "tests/fixtures/syllabi/sample.pdf")
        assert self._hook_result(repo).returncode == 0


class TestOffline:
    def test_public_build_makes_no_network_calls(self, vault_conn, tmp_path, monkeypatch):
        """publishing must never depend on a lookup service being up."""

        def refuse(*args, **kwargs):
            raise AssertionError("the build attempted a network connection")

        monkeypatch.setattr(socket.socket, "connect", refuse)
        monkeypatch.setattr(socket, "create_connection", refuse)

        payload, _ = publish.build_public_payload(vault_conn)
        export = tmp_path / "public.json"
        export.write_text(json.dumps(payload), encoding="utf-8")
        report = build(json.loads(export.read_text(encoding="utf-8")), tmp_path / "site")
        assert report.pages > 0


def _weasyprint_usable() -> bool:
    try:
        import weasyprint  # noqa: F401

        return True
    except Exception:
        return False


@pytest.mark.skipif(not _weasyprint_usable(), reason="weasyprint native libraries absent")
class TestPrintPdfs:
    def test_pdfs_render_with_course_code_in_the_text_layer(self, vault_conn, tmp_path):
        import pymupdf

        from vault.site.pdf import build_pdfs

        payload, _ = publish.build_public_payload(vault_conn)
        report = build_pdfs(payload, tmp_path / "pdf")
        assert report.skipped_reason is None
        names = {p.name for p in report.written}
        assert "demo-6100-semester-plan.pdf" in names
        assert "demo-6100-bibliography.pdf" in names
        assert "demo-6100-week-02.pdf" in names
        assert "deadlines.pdf" in names

        for path in report.written:
            assert path.stat().st_size > 500
            doc = pymupdf.open(path)
            assert 1 <= doc.page_count <= 40
            text = "".join(page.get_text() for page in doc)
            if path.name.startswith("demo-6100"):
                assert "DEMO 6100" in text
            doc.close()

    def test_no_chunk_text_reaches_any_pdf(self, vault_conn, tmp_path):
        import pymupdf

        from conftest import SENTINEL_BRIEF, SENTINEL_CHUNK
        from vault.site.pdf import build_pdfs

        payload, _ = publish.build_public_payload(vault_conn)
        report = build_pdfs(payload, tmp_path / "pdf")
        for path in report.written:
            doc = pymupdf.open(path)
            text = "".join(page.get_text() for page in doc)
            doc.close()
            assert SENTINEL_CHUNK not in text
            assert SENTINEL_BRIEF not in text
