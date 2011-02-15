from array import array
from nose.tools import eq_

import recommend


def test_symmetric_diff_count():
    def check(a, b, val):
        eq_(recommend.symmetric_diff_count(a, b), val)
    vals = [
        ([], [], 0),
        ([], [1], 1),
        ([1], [1], 0),
        ([], [1, 2], 2),
        ([], [1, 2, 3], 3),
        ([1, 2], [1, 3], 2),
        ([1, 2, 4], [1, 3], 3),
        ([1, 4], [1, 3], 2),
        ([1, 2, 4], [1, 2, 3], 2),
        ([1, 3, 5], [2, 4], 5),
        ([1, 3, 5], [1, 5], 1),
        ([1, 3, 5], [4, 5], 3),
    ]
    # Flip the inputs so we test in both directions.
    vals.extend([(b, a, n) for a, b, n in vals])
    vals.extend([(array('l', a), array('l', b), n) for a, b, n in vals])
    for a, b, val in vals:
        yield check, a, b, val


# The algorithm is in flux so this is minimal coverage.
def test_similarity():
    eq_(1/2., recommend.similarity([1], [1, 2]))
