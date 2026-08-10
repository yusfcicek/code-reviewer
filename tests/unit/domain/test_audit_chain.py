"""Step 2 — chaining, and what a broken chain looks like.

The verdict is a position and a reason, never a boolean. "Something is wrong
somewhere in these twelve hundred records" is not a thing an operator can act
on, and a tool that says it gets run once.

The other rule this file exists to pin: **unverifiable is not tampered.** A
deployment that has not configured a key is in that state on its first day, and
a verifier that cries wolf there is a verifier somebody turns off before it ever
sees a real tamper.
"""

from code_reviewer.domain.audit import GENESIS, ChainStatus, Seal, digest_of, sealed, verify

FIRST = {"verdict": "pass", "project": "1", "merge_request": "10"}
SECOND = {"verdict": "fail", "project": "1", "merge_request": "11"}
THIRD = {"verdict": "warn", "project": "1", "merge_request": "12"}


def _chain(*payloads, sign=None):
    """Builds a well-formed chain, the way the sink will."""
    entries = []
    previous = GENESIS
    for payload in payloads:
        seal = sealed(payload, previous, sign=sign)
        entries.append((seal, payload))
        previous = seal.digest
    return entries


def _signer(key_id="ops-2026"):
    """A stand-in signature: reversible, so the test can forge one."""
    return lambda digest: (f"sig-{digest}", key_id)


def _accepts(digest, signature, key_id):
    return signature == f"sig-{digest}" and key_id == "ops-2026"


class TestAnIntactChain:
    def test_an_untouched_chain_is_intact(self):
        verdict = verify(_chain(FIRST, SECOND, THIRD))

        assert verdict.status is ChainStatus.INTACT

    def test_it_says_how_many_it_checked(self):
        assert verify(_chain(FIRST, SECOND, THIRD)).checked == 3

    def test_an_empty_store_is_intact_rather_than_an_error(self):
        """Nothing to verify is not a failure. A deployment that has written no
        record yet must not read as compromised."""
        assert verify([]).status is ChainStatus.INTACT

    def test_the_first_record_names_the_genesis_value(self):
        seal, _ = _chain(FIRST)[0]

        assert seal.previous == GENESIS


class TestTampering:
    def test_an_edited_payload_fails_at_its_own_line(self):
        entries = _chain(FIRST, SECOND, THIRD)
        seal, payload = entries[1]
        entries[1] = (seal, dict(payload, verdict="pass"))

        verdict = verify(entries)

        assert verdict.status is ChainStatus.TAMPERED
        assert verdict.position == 2

    def test_the_reason_says_the_digest_disagrees(self):
        entries = _chain(FIRST, SECOND)
        seal, payload = entries[1]
        entries[1] = (seal, dict(payload, verdict="pass"))

        assert "digest" in verify(entries).reason.lower()

    def test_a_deleted_line_fails_at_the_line_that_followed_it(self):
        """And says the *chain* broke, not that a digest was wrong. An operator
        needs to know which of the two happened."""
        entries = _chain(FIRST, SECOND, THIRD)
        del entries[1]

        verdict = verify(entries)

        assert verdict.status is ChainStatus.TAMPERED
        assert verdict.position == 2
        assert "chain" in verdict.reason.lower()

    def test_two_lines_swapped_are_detected(self):
        entries = _chain(FIRST, SECOND, THIRD)
        entries[1], entries[2] = entries[2], entries[1]

        assert verify(entries).status is ChainStatus.TAMPERED

    def test_a_line_appended_by_hand_is_detected(self):
        entries = _chain(FIRST, SECOND)
        forged = Seal(previous=GENESIS, digest=digest_of(THIRD, GENESIS))
        entries.append((forged, THIRD))

        verdict = verify(entries)

        assert verdict.status is ChainStatus.TAMPERED
        assert verdict.position == 3

    def test_only_the_first_failure_is_reported(self):
        """A cascade of positions after the first is noise; the operator needs
        where it started."""
        entries = _chain(FIRST, SECOND, THIRD)
        entries[0] = (entries[0][0], dict(FIRST, verdict="fail"))

        assert verify(entries).position == 1


class TestSignatures:
    def test_a_correctly_signed_chain_is_intact(self):
        entries = _chain(FIRST, SECOND, sign=_signer())

        assert verify(entries, accepts=_accepts).status is ChainStatus.INTACT

    def test_it_says_how_many_were_signed(self):
        entries = _chain(FIRST, SECOND, sign=_signer())

        assert verify(entries, accepts=_accepts).signed == 2

    def test_a_forged_signature_is_tampering(self):
        entries = _chain(FIRST, SECOND, sign=_signer())
        seal, payload = entries[1]
        entries[1] = (Seal(seal.previous, seal.digest, "sig-nonsense", seal.key_id), payload)

        verdict = verify(entries, accepts=_accepts)

        assert verdict.status is ChainStatus.TAMPERED
        assert verdict.position == 2
        assert "signature" in verdict.reason.lower()

    def test_a_signature_from_an_unknown_key_is_tampering(self):
        """AC-8 — a validly-signed record from a key this store does not use
        is somebody else's record, appended here."""
        entries = _chain(FIRST, sign=_signer(key_id="somebody-elses-key"))

        assert verify(entries, accepts=_accepts).status is ChainStatus.TAMPERED

    def test_an_unsigned_chain_is_unverifiable_rather_than_tampered(self):
        """AC-9, and the finding this rule exists to prevent."""
        verdict = verify(_chain(FIRST, SECOND), accepts=_accepts)

        assert verdict.status is ChainStatus.UNVERIFIABLE
        assert "unsigned" in verdict.reason.lower()

    def test_an_unsigned_chain_still_has_its_links_checked(self):
        """Losing the signatures must not lose the cheaper guarantee."""
        entries = _chain(FIRST, SECOND)
        entries[0] = (entries[0][0], dict(FIRST, verdict="fail"))

        assert verify(entries, accepts=_accepts).status is ChainStatus.TAMPERED

    def test_with_no_verifier_signatures_are_unverifiable_not_wrong(self):
        """The state of a run that has the store but not the key."""
        verdict = verify(_chain(FIRST, sign=_signer()))

        assert verdict.status is ChainStatus.UNVERIFIABLE

    def test_a_partly_signed_chain_is_unverifiable(self):
        """Signing started midway, or stopped. Either way the store cannot say
        it is whole."""
        entries = _chain(FIRST)
        second = sealed(SECOND, entries[0][0].digest, sign=_signer())
        entries.append((second, SECOND))

        assert verify(entries, accepts=_accepts).status is ChainStatus.UNVERIFIABLE


class TestTheVerdict:
    def test_an_intact_verdict_names_no_position(self):
        assert verify(_chain(FIRST)).position == 0

    def test_a_verdict_carries_no_record_content(self):
        """The verifier reports positions. Whoever reads its output may not be
        the person allowed to read the records."""
        entries = _chain(FIRST, SECOND)
        entries[1] = (entries[1][0], dict(SECOND, project="secret-project-name"))

        assert "secret-project-name" not in verify(entries).reason
