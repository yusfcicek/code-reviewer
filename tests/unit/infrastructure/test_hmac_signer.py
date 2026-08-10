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


class TestAKeyring:
    """Level 30 — one key signs, several verify.

    Rotation is the routine operation this repository could not survive: with
    one signer holding one key, every record written under the previous key
    read as `tampered`. A keyring signs with the current key and can still
    confirm what a retired one signed; a key it does not hold at all is
    *unknown*, which is not the same as *wrong*.
    """

    CURRENT = "current-key-material-long-enough"
    RETIRED = "retired-key-material-long-enough"

    def _ring(self):
        from code_reviewer.infrastructure.governance.signing import HmacSigner, Keyring

        return Keyring(
            signing=HmacSigner(self.CURRENT, key_id="2026-key"),
            retired=(HmacSigner(self.RETIRED, key_id="2025-key"),),
        )

    def test_it_signs_with_the_current_key_only(self):
        """AC-4, C-1. Otherwise 'retired' is a label rather than a property."""
        ring = self._ring()

        _, key_id = ring.sign("a-digest")

        assert key_id == "2026-key"
        assert ring.key_id == "2026-key"

    def test_it_accepts_what_the_retired_key_signed(self):
        """AC-1. The whole point: history stays readable across a rotation."""
        from code_reviewer.infrastructure.governance.signing import HmacSigner

        old = HmacSigner(self.RETIRED, key_id="2025-key")
        signature, key_id = old.sign("a-digest")

        assert self._ring().accepts("a-digest", signature, key_id) is True

    def test_it_accepts_what_the_current_key_signed(self):
        ring = self._ring()
        signature, key_id = ring.sign("a-digest")

        assert ring.accepts("a-digest", signature, key_id) is True

    def test_a_key_it_does_not_hold_is_unknown_rather_than_wrong(self):
        """AC-2, C-2. `None` is the answer that stops a rotation from reading
        as a forgery, and a boolean cannot carry it."""
        assert self._ring().accepts("a-digest", "any-signature", "1999-key") is None

    def test_a_wrong_signature_under_a_held_key_is_wrong(self):
        """AC-3, C-3. Nothing is softened where the answer is known."""
        assert self._ring().accepts("a-digest", "not-a-signature", "2026-key") is False

    def test_it_is_signing(self):
        assert self._ring().is_signing is True

    def test_a_retired_key_that_is_too_short_is_refused(self):
        """AC-6, C-6. A weak key does not become acceptable by being old."""
        import pytest

        from code_reviewer.infrastructure.governance.signing import HmacSigner

        with pytest.raises(ValueError, match="too short"):
            HmacSigner("short", key_id="2025-key")

    def test_two_retired_keys_may_not_share_a_name(self):
        """A key id is what a record names; two keys answering to one name make
        the record's attribution a coin flip."""
        import pytest

        from code_reviewer.infrastructure.governance.signing import HmacSigner, Keyring

        with pytest.raises(ValueError, match="twice"):
            Keyring(
                signing=HmacSigner(self.CURRENT, key_id="same"),
                retired=(HmacSigner(self.RETIRED, key_id="same"),),
            )

    def test_no_key_material_reaches_its_repr(self):
        """AC-8, over the retired keys too. The five tests Level 24 wrote were
        about one key; a keyring holds several."""
        text = repr(self._ring())

        assert self.CURRENT not in text
        assert self.RETIRED not in text
        assert "2025-key" in text and "2026-key" in text


class TestRetiredKeysFromTheEnvironment:
    """AC-7, D-4. One variable per key, named by its id, so nothing has to be
    parsed out of secret material."""

    def test_a_retired_key_is_read_and_verifies(self):
        from code_reviewer.infrastructure.governance.signing import HmacSigner, signer_from_environment

        signer = signer_from_environment(
            {
                "REVIEW_AUDIT_KEY": "current-key-material-long-enough",
                "REVIEW_AUDIT_KEY_ID": "2026-key",
                "REVIEW_AUDIT_KEY_RETIRED_2025-key": "retired-key-material-long-enough",
            }
        )

        old = HmacSigner("retired-key-material-long-enough", key_id="2025-key")
        signature, key_id = old.sign("a-digest")

        assert signer.accepts("a-digest", signature, key_id) is True
        assert signer.key_id == "2026-key"

    def test_the_id_comes_from_the_variable_name_in_the_case_it_was_written(self):
        """A key id is compared to what a record wrote, so the case matters."""
        from code_reviewer.infrastructure.governance.signing import signer_from_environment

        signer = signer_from_environment(
            {
                "REVIEW_AUDIT_KEY": "current-key-material-long-enough",
                "REVIEW_AUDIT_KEY_RETIRED_old-2025": "retired-key-material-long-enough",
            }
        )

        assert signer.accepts("d", "s", "old-2025") is False
        assert signer.accepts("d", "s", "OLD-2025") is None

    def test_an_unusable_retired_key_costs_the_review_nothing(self):
        """The rule since Level 20's C-9: an accountability feature may not fail
        the thing it accounts for. The current key still signs."""
        from code_reviewer.infrastructure.governance.signing import signer_from_environment

        signer = signer_from_environment(
            {
                "REVIEW_AUDIT_KEY": "current-key-material-long-enough",
                "REVIEW_AUDIT_KEY_ID": "2026-key",
                "REVIEW_AUDIT_KEY_RETIRED_2025-KEY": "short",
            }
        )

        assert signer.is_signing
        assert signer.accepts("d", "s", "2025-key") is None

    def test_retired_keys_with_no_current_key_still_verify(self):
        """A deployment that has stopped signing can still read its history."""
        from code_reviewer.infrastructure.governance.signing import HmacSigner, signer_from_environment

        signer = signer_from_environment(
            {"REVIEW_AUDIT_KEY_RETIRED_2025-key": "retired-key-material-long-enough"}
        )

        old = HmacSigner("retired-key-material-long-enough", key_id="2025-key")
        signature, key_id = old.sign("a-digest")

        assert signer.is_signing is False
        assert signer.accepts("a-digest", signature, key_id) is True

    def test_no_retired_key_leaves_the_signer_as_it_was(self):
        from code_reviewer.infrastructure.governance.signing import HmacSigner, signer_from_environment

        signer = signer_from_environment(
            {"REVIEW_AUDIT_KEY": "current-key-material-long-enough", "REVIEW_AUDIT_KEY_ID": "2026-key"}
        )

        assert isinstance(signer, HmacSigner)
