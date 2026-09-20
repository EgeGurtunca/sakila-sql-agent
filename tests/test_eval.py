from eval.run_eval import same_result


def test_order_insensitive_and_float_tolerant():
    assert same_result([("b", 2), ("a", 1.0000001)], [("a", 1.0), ("b", 2)])


def test_extra_leading_column_is_tolerated():
    assert same_result([(1, "KARL", "SEAL", 221.55)], [("KARL", "SEAL", 221.55)])


def test_different_values_fail():
    assert not same_result([(999,)], [(1000,)])
    assert not same_result([], [(1,)])
