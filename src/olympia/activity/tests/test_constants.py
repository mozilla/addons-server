from django.utils.translation import gettext_lazy as _

import pytest

from olympia.constants.activity import (
    LOG,
    LOG_HIDE_DEVELOPER,
    LOG_OBSOLETE,
    LOG_REVIEW_QUEUE_DEVELOPER,
)


def is_translated(value):
    """Return True if `value` is a translated string. It simply looks at the
    type: since translated strings for constants should be lazy, their type
    should be a lazy proxy, not `str`."""
    return not isinstance(value, str)


def test_is_translated():
    assert is_translated(_('Add-on'))
    assert not is_translated('Add-on')


@pytest.mark.parametrize(
    'action',
    [
        action
        for action in LOG
        if action.id not in LOG_HIDE_DEVELOPER and action.id not in LOG_OBSOLETE
    ],
)
def test_format_strings_for_actions_developers_can_see_are_translated(action):
    # Any action that is available for developers to see should have its
    # format string translated.
    assert is_translated(action.format)


@pytest.mark.parametrize(
    'action',
    [
        action
        for action in LOG
        if action.id in LOG_REVIEW_QUEUE_DEVELOPER and action.id not in LOG_OBSOLETE
    ],
)
def test_short_strings_for_actions_available_through_api_are_translated(action):
    # ActivityLogSerializer potentially exposes `short` ; that serializer
    # is used in VersionReviewNotesViewSet which returns activities in
    # LOG_REVIEW_QUEUE_DEVELOPER and is available to developers, so those
    # strings should be translated.
    assert is_translated(action.short)
