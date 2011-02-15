"""
Helper functions for calculating correlation coefficients between lists of
items.

Check the function docs, they expect specific preconditions.
"""

# Placeholders for the fast functions implemented in C.


def symmetric_diff_count(xs, ys):
    return len(set(xs).symmetric_difference(ys))


def similarity(xs, ys):
    return 1. / (1. + symmetric_diff_count(xs, ys))


try:
    from _recommend import symmetric_diff_count, similarity
except ImportError:
    pass
