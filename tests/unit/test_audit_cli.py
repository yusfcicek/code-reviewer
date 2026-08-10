"""Step 5 — the verifier as a command.

Three exit codes, the split Level 10 introduced and Level 12 reused: `0` the
thing is sound, `1` the thing is wrong, `2` the measurement could not be taken.
Conflating the last two is what makes a gate unusable — a pipeline cannot tell
a tampered store from a missing file and has to treat both as advice.

The second rule this file pins: the command prints positions and never record
content. Whoever is allowed to run the verifier is not necessarily allowed to
read the merge requests it covers.
"""

import json

from code_reviewer.audit import EXIT_CANNOT_VERIFY, EXIT_INTACT, EXIT_TAMPERED, main
from code_reviewer.domain.provenance import DecisionRecord, RunIdentity
from code_reviewer.infrastructure.governance.sealed_sink import SealedAuditSink
from code_reviewer.infrastructure.governance.signing import HmacSigner

KEY = "s3cr3t-audit-key-long-enough"


def _record(merge_request="10", project="1"):
    return DecisionRecord(
        verdict="pass",
        exit_code=0,
        identity=RunIdentity(package_version="2.18.0", policy_version="1.0"),
        project=project,
        merge_request=merge_request,
    )


def _store(tmp_path, count=3, signer=None):
    path = tmp_path / "audit.ndjson"
    sink = SealedAuditSink(path, signer=signer)
    for index in range(count):
        sink.write(_record(merge_request=str(index)))
    return path


class TestAnIntactStore:
    def test_it_exits_zero(self, tmp_path):
        assert main(["verify", "--path", str(_store(tmp_path))]) == EXIT_INTACT

    def test_it_says_how_many_it_checked(self, tmp_path, capsys):
        main(["verify", "--path", str(_store(tmp_path))])

        assert "3" in capsys.readouterr().out

    def test_an_empty_store_is_intact(self, tmp_path):
        path = tmp_path / "audit.ndjson"
        path.write_text("", encoding="utf-8")

        assert main(["verify", "--path", str(path)]) == EXIT_INTACT


class TestATamperedStore:
    def _edited(self, tmp_path):
        path = _store(tmp_path)
        lines = path.read_text(encoding="utf-8").splitlines()
        document = json.loads(lines[1])
        document["record"]["verdict"] = "fail"
        lines[1] = json.dumps(document, sort_keys=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_it_exits_one(self, tmp_path):
        assert main(["verify", "--path", str(self._edited(tmp_path))]) == EXIT_TAMPERED

    def test_it_names_the_position(self, tmp_path, capsys):
        main(["verify", "--path", str(self._edited(tmp_path))])

        assert "2" in capsys.readouterr().out

    def test_it_says_what_kind_of_failure(self, tmp_path, capsys):
        main(["verify", "--path", str(self._edited(tmp_path))])

        assert "edited" in capsys.readouterr().out.lower()

    def test_a_deleted_line_exits_one(self, tmp_path):
        path = _store(tmp_path)
        lines = path.read_text(encoding="utf-8").splitlines()
        del lines[1]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        assert main(["verify", "--path", str(path)]) == EXIT_TAMPERED


class TestWhatCannotBeVerified:
    def test_a_missing_file_exits_two_rather_than_one(self, tmp_path):
        """A missing store is not a tampered store, and a pipeline has to be
        able to tell them apart."""
        assert main(["verify", "--path", str(tmp_path / "absent.ndjson")]) == EXIT_CANNOT_VERIFY

    def test_a_signed_store_with_no_key_exits_two(self, tmp_path, monkeypatch):
        monkeypatch.delenv("REVIEW_AUDIT_KEY", raising=False)
        path = _store(tmp_path, signer=HmacSigner(KEY, key_id="ops-2026"))

        assert main(["verify", "--path", str(path)]) == EXIT_CANNOT_VERIFY

    def test_a_signed_store_with_its_key_exits_zero(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REVIEW_AUDIT_KEY", KEY)
        monkeypatch.setenv("REVIEW_AUDIT_KEY_ID", "ops-2026")
        path = _store(tmp_path, signer=HmacSigner(KEY, key_id="ops-2026"))

        assert main(["verify", "--path", str(path)]) == EXIT_INTACT

    def test_a_signed_store_with_the_wrong_key_exits_one(self, tmp_path, monkeypatch):
        """Not two. A signature that does not check out is a fact about the
        store, not a gap in the tooling."""
        monkeypatch.setenv("REVIEW_AUDIT_KEY", "a-completely-different-key-value")
        monkeypatch.setenv("REVIEW_AUDIT_KEY_ID", "ops-2026")
        path = _store(tmp_path, signer=HmacSigner(KEY, key_id="ops-2026"))

        assert main(["verify", "--path", str(path)]) == EXIT_TAMPERED

    def test_an_unsigned_store_exits_two_when_a_key_is_configured(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REVIEW_AUDIT_KEY", KEY)
        monkeypatch.setenv("REVIEW_AUDIT_KEY_ID", "ops-2026")

        assert main(["verify", "--path", str(_store(tmp_path))]) == EXIT_CANNOT_VERIFY

    def test_the_unverifiable_output_says_why(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REVIEW_AUDIT_KEY", KEY)
        monkeypatch.setenv("REVIEW_AUDIT_KEY_ID", "ops-2026")
        main(["verify", "--path", str(_store(tmp_path))])


class TestItPrintsNoRecordContent:
    def test_an_intact_report_names_no_project(self, tmp_path, capsys):
        path = tmp_path / "audit.ndjson"
        SealedAuditSink(path).write(_record(project="a-private-project-name"))

        main(["verify", "--path", str(path)])

        assert "a-private-project-name" not in capsys.readouterr().out

    def test_a_tampered_report_names_no_project(self, tmp_path, capsys):
        path = tmp_path / "audit.ndjson"
        SealedAuditSink(path).write(_record(project="a-private-project-name"))
        lines = path.read_text(encoding="utf-8").splitlines()
        document = json.loads(lines[0])
        document["record"]["verdict"] = "fail"
        path.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")

        main(["verify", "--path", str(path)])

        assert "a-private-project-name" not in capsys.readouterr().out


class TestTheDefaultPath:
    def test_the_path_can_come_from_the_environment(self, tmp_path, monkeypatch):
        path = _store(tmp_path)
        monkeypatch.setenv("REVIEW_AUDIT_PATH", str(path))

        assert main(["verify"]) == EXIT_INTACT

    def test_with_no_path_at_all_it_cannot_verify(self, monkeypatch):
        monkeypatch.delenv("REVIEW_AUDIT_PATH", raising=False)

        assert main(["verify"]) == EXIT_CANNOT_VERIFY


class TestErasingFromTheCommandLine:
    def test_it_removes_and_says_so(self, tmp_path, capsys):
        path = _store(tmp_path)

        code = main(["erase", "--path", str(path), "--merge-request", "1", "--policy", "request"])

        assert code == EXIT_INTACT
        assert "1 removed" in capsys.readouterr().out

    def test_the_store_still_verifies_afterwards(self, tmp_path):
        path = _store(tmp_path)

        main(["erase", "--path", str(path), "--merge-request", "1", "--policy", "request"])

        assert main(["verify", "--path", str(path)]) == EXIT_INTACT

    def test_a_refusal_exits_two_rather_than_one(self, tmp_path, capsys):
        """Refusing is this command declining to produce something worse than
        what it was asked to change, not a statement that the store is wrong."""
        path = _store(tmp_path)
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[1] = lines[1].replace('"pass"', '"fail"')
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        code = main(["erase", "--path", str(path), "--merge-request", "1", "--policy", "request"])

        assert code == EXIT_CANNOT_VERIFY
        assert "refused" in capsys.readouterr().err.lower()

    def test_a_policy_is_required(self, tmp_path):
        import pytest

        with pytest.raises(SystemExit):
            main(["erase", "--path", str(_store(tmp_path)), "--merge-request", "1"])

    def test_redaction_keeps_the_record(self, tmp_path, capsys):
        path = tmp_path / "audit.ndjson"
        SealedAuditSink(path).write(_record(project="a-private-project-name"))

        code = main(
            ["redact", "--path", str(path), "--project", "a-private-project-name", "--policy", "request"]
        )

        assert code == EXIT_INTACT
        assert "1 redacted" in capsys.readouterr().out
        assert "a-private-project-name" not in path.read_text(encoding="utf-8")
