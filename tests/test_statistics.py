from src.statistics import bootstrap_accuracy_ci, mcnemar_exact


def test_bootstrap_accuracy_is_reproducible_and_contains_estimate():
    rows = [
        {"acceptable_match": value}
        for value in [True, True, True, False, False]
    ]
    first = bootstrap_accuracy_ci(rows, samples=500, seed=7)
    second = bootstrap_accuracy_ci(rows, samples=500, seed=7)
    assert first == second
    estimate, low, high = first
    assert estimate == 0.6
    assert low <= estimate <= high


def test_mcnemar_pairs_by_id_not_row_order():
    left = [
        {"cbro_id": "a", "acceptable_match": True},
        {"cbro_id": "b", "acceptable_match": False},
        {"cbro_id": "c", "acceptable_match": True},
    ]
    right = [
        {"cbro_id": "c", "acceptable_match": False},
        {"cbro_id": "b", "acceptable_match": True},
        {"cbro_id": "a", "acceptable_match": True},
    ]
    result = mcnemar_exact(left, right)
    assert result["n_paired"] == 3
    assert result["left_only_correct"] == 1
    assert result["right_only_correct"] == 1
    assert result["p_value"] == 1.0
