"""Step 1 — what a sealed record is.

The seal is the whole of Level 24's integrity claim, so it is worth being
precise about what it does *not* claim. An operator holding both the key and
the store can forge any of this. What a seal buys is that the cheap tampers —
edit a line, delete a line, reorder two — stop being invisible, and the spec
says that rather than implying more.
"""

import pytest

from code_reviewer.domain.audit import GENESIS, Seal, digest_of


class TestWhatASealCarries:
    def test_a_seal_names_the_record_before_it(self):
        seal = Seal(previous=GENESIS, digest="a" * 64)

        assert seal.previous == GENESIS

    def test_the_first_seal_carries_a_stated_genesis_rather_than_an_empty_string(self):
        """AC-4. "This is the first record" and "somebody removed the field"
        must be different states; an empty string is both."""
        assert GENESIS
        assert GENESIS != ""

    def test_a_signature_needs_a_key_id(self):
        """A signature nothing can attribute reads as verified and names
        nothing, which is worse than no signature at all."""
        with pytest.raises(ValueError):
            Seal(previous=GENESIS, digest="a" * 64, signature="deadbeef")

    def test_a_key_id_without_a_signature_is_refused_too(self):
        with pytest.raises(ValueError):
            Seal(previous=GENESIS, digest="a" * 64, key_id="ops-2026")

    def test_an_unsigned_seal_is_allowed_and_says_so(self):
        seal = Seal(previous=GENESIS, digest="a" * 64)

        assert not seal.is_signed

    def test_a_signed_seal_says_so(self):
        seal = Seal(previous=GENESIS, digest="a" * 64, signature="deadbeef", key_id="ops-2026")

        assert seal.is_signed

    def test_a_seal_with_no_digest_is_refused(self):
        with pytest.raises(ValueError):
            Seal(previous=GENESIS, digest="")

    def test_a_seal_with_no_predecessor_is_refused(self):
        """Not the same as the genesis value, which is a predecessor."""
        with pytest.raises(ValueError):
            Seal(previous="", digest="a" * 64)


PAYLOAD = {"verdict": "fail", "exit_code": 1, "project": "42"}


class TestTheDigest:
    def test_the_same_payload_digests_the_same(self):
        assert digest_of(PAYLOAD) == digest_of(dict(PAYLOAD))

    def test_key_order_does_not_change_the_digest(self):
        """The sink serialises with sorted keys, and the digest has to agree
        with that rather than with insertion order."""
        reordered = {"project": "42", "exit_code": 1, "verdict": "fail"}

        assert digest_of(PAYLOAD) == digest_of(reordered)

    def test_one_changed_character_changes_the_digest(self):
        edited = dict(PAYLOAD, verdict="pass")

        assert digest_of(PAYLOAD) != digest_of(edited)

    def test_the_predecessor_is_part_of_what_is_digested(self):
        """Otherwise reordering two identical-payload records is invisible."""
        assert digest_of(PAYLOAD, previous="a" * 64) != digest_of(PAYLOAD, previous="b" * 64)

    def test_the_digest_is_hex_and_fixed_width(self):
        value = digest_of(PAYLOAD)

        assert len(value) == 64
        assert all(character in "0123456789abcdef" for character in value)

    def test_an_empty_payload_is_refused(self):
        """A record with nothing in it is not a record."""
        with pytest.raises(ValueError):
            digest_of({})

    def test_a_payload_that_will_not_serialise_is_refused_rather_than_guessed_at(self):
        with pytest.raises(ValueError):
            digest_of({"when": object()})
