from django.test import TestCase

from deployments.tasks import outcomes


class FetchFailureVocabularyTestCase(TestCase):
    """`FETCH_FAILURE_MESSAGES` must classify every outcome, not just the ones remembered.

    Every non-benign `Outcome` has to be either a key in the map or named in
    `HANDLED_ELSEWHERE` with a reason. Without this, an outcome added to the enum and never
    wired up records nothing and nobody notices -- which is exactly how
    `constraint_out_of_range` and `no_matching_time` went missing before this test existed.
    """

    def test_fetch_failure_messages_is_exhaustive(self):
        classified = set(outcomes.FETCH_FAILURE_MESSAGES) | set(outcomes.HANDLED_ELSEWHERE)
        all_outcomes = set(outcomes.Outcome)

        unclassified = all_outcomes - outcomes.BENIGN_OUTCOMES - classified
        self.assertEqual(unclassified, set(), "outcome(s) not in the map or HANDLED_ELSEWHERE")

        expected = all_outcomes - outcomes.BENIGN_OUTCOMES - set(outcomes.HANDLED_ELSEWHERE)
        self.assertEqual(expected, set(outcomes.FETCH_FAILURE_MESSAGES))

    def test_handled_elsewhere_entries_carry_a_reason(self):
        for outcome, reason in outcomes.HANDLED_ELSEWHERE.items():
            self.assertTrue(reason, f"{outcome} has no reason recorded")

    def test_benign_outcomes_are_not_also_in_the_map(self):
        # Meant to partition Outcome between them (with HANDLED_ELSEWHERE); overlap would
        # mean a benign outcome that also records a SystemMessage.
        self.assertEqual(
            outcomes.BENIGN_OUTCOMES & set(outcomes.FETCH_FAILURE_MESSAGES),
            set(),
        )
