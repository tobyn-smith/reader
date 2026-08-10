"""the tests that keep private material off a public url.

these run against a fixture database holding sentinel strings in every place
that must not publish: chunk text, brief text, an instructor email, a private
note. if any sentinel appears anywhere in the public build, something upstream
broke and the build must not ship.
"""

import json

import pytest

from vault import publish
from vault.site.build import build, build_private_payload

from conftest import SENTINEL_BRIEF, SENTINEL_CHUNK, SENTINEL_EMAIL

SENTINELS = [SENTINEL_CHUNK, SENTINEL_BRIEF, SENTINEL_EMAIL, "private thought, stays home"]


def read_everything(root) -> str:
    blobs = []
    for path in root.rglob("*"):
        if path.is_file():
            blobs.append(path.read_bytes().decode("utf-8", errors="ignore"))
    return "\n".join(blobs)


class TestExportAllowlist:
    def test_payload_contains_only_allowlisted_fields(self, vault_conn):
        payload, _ = publish.build_public_payload(vault_conn)
        assert publish.check_payload(payload) == []

    def test_new_schema_column_does_not_slip_through(self, vault_conn):
        payload, _ = publish.build_public_payload(vault_conn)
        # simulate someone adding a column and forgetting the allowlist
        payload["courses"][0]["sessions"][0]["private_marginalia"] = "oops"
        assert publish.check_payload(payload) == ["session.private_marginalia"]

    def test_withheld_fields_never_appear(self, vault_conn):
        payload, _ = publish.build_public_payload(vault_conn)
        text = json.dumps(payload)
        for sentinel in SENTINELS:
            assert sentinel not in text

    def test_sensitive_course_is_dropped_entirely(self, vault_conn):
        vault_conn.execute("update course set sensitive = 1")
        vault_conn.commit()
        payload, summary = publish.build_public_payload(vault_conn)
        assert payload["courses"] == []
        assert summary.courses_withheld == ["DEMO 6100"]

    def test_shareable_note_is_included_private_note_is_not(self, vault_conn):
        payload, summary = publish.build_public_payload(vault_conn)
        notes = payload["courses"][0]["notes"]
        assert [n["body"] for n in notes] == ["shareable observation"]
        assert summary.notes_withheld == 1

    def test_export_write_refuses_a_bad_payload(self, vault_conn, tmp_path, monkeypatch):
        real = publish.build_public_payload

        def poisoned(conn):
            payload, summary = real(conn)
            payload["courses"][0]["instructor_email"] = SENTINEL_EMAIL
            return payload, summary

        monkeypatch.setattr(publish, "build_public_payload", poisoned)
        with pytest.raises(ValueError, match="allowlist"):
            publish.write_public_export(vault_conn, tmp_path / "public.json")
        assert not (tmp_path / "public.json").exists()


class TestPublicBuildLeaks:
    def test_no_sentinel_anywhere_in_the_public_site(self, vault_conn, tmp_path):
        payload, _ = publish.build_public_payload(vault_conn)
        build(payload, tmp_path / "site", private=False)
        everything = read_everything(tmp_path / "site")
        for sentinel in SENTINELS:
            assert sentinel not in everything

    def test_public_build_needs_no_database(self, vault_conn, tmp_path):
        """the payload round trips through json, which is all ci ever has."""
        payload, _ = publish.build_public_payload(vault_conn)
        export = tmp_path / "public.json"
        export.write_text(json.dumps(payload), encoding="utf-8")
        vault_conn.close()

        from vault.site.build import load_public_payload

        rebuilt = load_public_payload(export)
        report = build(rebuilt, tmp_path / "site", private=False)
        assert report.pages > 4

    def test_missing_reading_is_marked(self, vault_conn, tmp_path):
        payload, _ = publish.build_public_payload(vault_conn)
        build(payload, tmp_path / "site", private=False)
        week = (tmp_path / "site" / "course" / "demo-6100" / "week-02.html").read_text(
            encoding="utf-8"
        )
        assert "missing" in week
        assert "The Unread Reading" in week

    def test_ai_policy_shown_on_course_and_work_pages(self, vault_conn, tmp_path):
        payload, _ = publish.build_public_payload(vault_conn)
        build(payload, tmp_path / "site", private=False)
        root = tmp_path / "site" / "course" / "demo-6100"
        assert "prohibited" in (root / "index.html").read_text(encoding="utf-8")
        work_pages = list((root / "work").glob("*.html"))
        assert work_pages
        assert all("prohibited" in p.read_text(encoding="utf-8") for p in work_pages)


class TestPrivateBuild:
    def test_private_build_contains_the_full_text(self, vault_conn, tmp_path):
        payload = build_private_payload(vault_conn)
        build(payload, tmp_path / "site", private=True)
        everything = read_everything(tmp_path / "site")
        assert SENTINEL_CHUNK in everything
        assert SENTINEL_BRIEF in everything

    def test_private_brief_is_watermarked(self, vault_conn, tmp_path):
        payload = build_private_payload(vault_conn)
        build(payload, tmp_path / "site", private=True)
        everything = read_everything(tmp_path / "site")
        assert "Model generated" in everything
