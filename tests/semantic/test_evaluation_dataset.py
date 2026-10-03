from scripts.evaluate import _percentile
from scripts.evaluation_cases import EVALUATION_CASES, TUNING_CASES


def test_held_out_set_has_six_bilingual_examples_per_class() -> None:
    assert len(EVALUATION_CASES) == 12
    assert sum(not case.malicious for case in EVALUATION_CASES) == 6
    assert sum(case.malicious for case in EVALUATION_CASES) == 6
    assert {case.language for case in EVALUATION_CASES} == {"en", "pl"}
    assert len({case.case_id for case in EVALUATION_CASES}) == len(EVALUATION_CASES)


def test_threshold_tuning_examples_are_disjoint_from_held_out_evaluation() -> None:
    evaluation_ids = {case.case_id for case in EVALUATION_CASES}
    tuning_ids = {case.case_id for case in TUNING_CASES}
    assert len(TUNING_CASES) >= 4
    assert evaluation_ids.isdisjoint(tuning_ids)


def test_percentiles_are_defined_for_small_runs() -> None:
    assert _percentile([], 50) is None
    assert _percentile([3.0], 50) == 3.0
    assert _percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.5
    assert _percentile([1.0, 2.0, 3.0, 4.0], 95) == 3.85
