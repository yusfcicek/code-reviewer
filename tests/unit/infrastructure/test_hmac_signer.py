"""Step 3 — the signer, and the refusal to invent a key.

A key this repository could produce is a key an attacker who has this
repository can produce. So there is no generated key, no bundled key and no
derived-from-the-hostname key: the adapter reads what the deployment supplies
and refuses to construct without it.

The last group is the one that would actually be a credential leak. Level 20
wrote that test for the decision record, where the material was identifiers;
here the material is the key itself.
"""

import logging

import pytest

from code_reviewer.infrastructure.governance.signing import (
    MINIMUM_KEY_BYTES,
    HmacSigner,
    NullSigner,
    signer_from_environment,
)

KEY = "s3cr3t-audit-key-long-enough-to-be-real"


class TestTheHmacSigner:
    def test_it_signs_a_digest(self):
        signature, key_id = HmacSigner(KEY, key_id="ops-2026").sign("a" * 64)

        assert signature
        assert key_id == "ops-2026"

    def test_the_same_digest_signs_the_same(self):
        signer = HmacSigner(KEY, key_id="ops-2026")

        assert signer.sign("a" * 64) == signer.sign("a" * 64)

    def test_a_different_digest_signs_differently(self):
        signer = HmacSigner(KEY, key_id="ops-2026")

        assert signer.sign("a" * 64) != signer.sign("b" * 64)

    def test_a_different_key_signs_differently(self):
        first = HmacSigner(KEY, key_id="ops-2026").sign("a" * 64)[0]
        second = HmacSigner(KEY + "x", key_id="ops-2026").sign("a" * 64)[0]

        assert first != second

    def test_it_accepts_its_own_signature(self):
        signer = HmacSigner(KEY, key_id="ops-2026")
        signature, key_id = signer.sign("a" * 64)

        assert signer.accepts("a" * 64, signature, key_id)

    def test_it_rejects_a_signature_over_another_digest(self):
        signer = HmacSigner(KEY, key_id="ops-2026")
        signature, key_id = signer.sign("a" * 64)

        assert not signer.accepts("b" * 64, signature, key_id)

    def test_it_rejects_a_signature_attributed_to_another_key(self):
        """AC-8 — a validly-signed record from somebody else's key is somebody
        else's record, appended here."""
        signer = HmacSigner(KEY, key_id="ops-2026")
        signature, _ = signer.sign("a" * 64)

        assert not signer.accepts("a" * 64, signature, "somebody-elses-key")

    def test_it_rejects_nonsense_without_raising(self):
        signer = HmacSigner(KEY, key_id="ops-2026")

        assert not signer.accepts("a" * 64, "not-hex-at-all", "ops-2026")


class TestItRefusesToInventAKey:
    def test_an_empty_key_is_refused(self):
        with pytest.raises(ValueError):
            HmacSigner("", key_id="ops-2026")

    def test_a_short_key_is_refused(self):
        with pytest.raises(ValueError):
            HmacSigner("x" * (MINIMUM_KEY_BYTES - 1), key_id="ops-2026")

    def test_the_refusal_does_not_quote_the_key(self):
        with pytest.raises(ValueError) as caught:
            HmacSigner("hunter2-secret", key_id="ops-2026")

        assert "hunter2-secret" not in str(caught.value)

    def test_a_key_with_no_id_is_refused(self):
        """An unattributable signature is what the domain already refuses."""
        with pytest.raises(ValueError):
            HmacSigner(KEY, key_id="")


class TestTheKeyNeverEscapes:
    """AC-19. The one test in this repository whose subject is real key material."""

    def test_it_is_not_in_the_repr(self):
        assert KEY not in repr(HmacSigner(KEY, key_id="ops-2026"))

    def test_it_is_not_in_the_string_form(self):
        assert KEY not in str(HmacSigner(KEY, key_id="ops-2026"))

    def test_it_is_not_logged_when_the_signer_is_built(self, caplog):
        with caplog.at_level(logging.DEBUG):
            signer_from_environment({"REVIEW_AUDIT_KEY": KEY, "REVIEW_AUDIT_KEY_ID": "ops-2026"})

        assert KEY not in caplog.text

    def test_it_is_not_in_the_signature(self):
        signature, _ = HmacSigner(KEY, key_id="ops-2026").sign("a" * 64)

        assert KEY not in signature

    def test_it_is_not_in_the_key_id(self):
        assert KEY not in HmacSigner(KEY, key_id="ops-2026").key_id


class TestBuildingFromTheEnvironment:
    def test_a_configured_key_produces_a_signer(self):
        signer = signer_from_environment({"REVIEW_AUDIT_KEY": KEY, "REVIEW_AUDIT_KEY_ID": "ops-2026"})

        assert isinstance(signer, HmacSigner)

    def test_no_key_produces_a_null_signer_rather_than_an_error(self):
        """AC-2 — a deployment with no key writes unsigned records and keeps
        reviewing. An accountability feature may not fail what it accounts for."""
        assert isinstance(signer_from_environment({}), NullSigner)

    def test_no_key_is_logged_once_so_the_omission_is_visible(self, caplog):
        with caplog.at_level(logging.INFO):
            signer_from_environment({})

        assert "unsigned" in caplog.text.lower()

    def test_a_key_with_no_id_falls_back_to_a_stated_default(self):
        signer = signer_from_environment({"REVIEW_AUDIT_KEY": KEY})

        assert signer.key_id

    def test_an_unusable_key_produces_a_null_signer_and_says_why(self, caplog):
        """Refusing to start would make a mistyped key cost every review."""
        with caplog.at_level(logging.WARNING):
            signer = signer_from_environment({"REVIEW_AUDIT_KEY": "short"})

        assert isinstance(signer, NullSigner)
        assert "short" not in caplog.text.replace("too short", "")


class TestTheNullSigner:
    def test_it_signs_nothing(self):
        assert NullSigner().sign("a" * 64) == ("", "")

    def test_it_says_it_is_not_signing(self):
        assert not NullSigner().is_signing

    def test_a_real_signer_says_it_is(self):
        assert HmacSigner(KEY, key_id="ops-2026").is_signing

    def test_it_accepts_nothing(self):
        """A verifier handed one must report unverifiable, not intact."""
        assert not NullSigner().accepts("a" * 64, "anything", "ops-2026")
