from django.utils import translation

import pytest

from unittest.mock import Mock

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo import LOG
from olympia.amo.tests import addon_factory, days_ago, user_factory
from olympia.amo.tests.test_helpers import render
from olympia.devhub.templatetags import jinja_helpers


pytestmark = pytest.mark.django_db


def test_dev_page_title():
    translation.activate('en-US')
    request = Mock()
    addon = Mock()
    addon.name = 'name'
    ctx = {'request': request, 'addon': addon}

    title = 'Oh hai!'
    s1 = render('{{ dev_page_title("%s") }}' % title, ctx)
    s2 = render('{{ page_title("%s :: Developer Hub") }}' % title, ctx)
    assert s1 == s2

    s1 = render('{{ dev_page_title() }}', ctx)
    s2 = render('{{ page_title("Developer Hub") }}', ctx)
    assert s1 == s2

    s1 = render('{{ dev_page_title("%s", addon) }}' % title, ctx)
    s2 = render(f'{{{{ page_title("{title} :: {addon.name}") }}}}', ctx)
    assert s1 == s2


def test_summarize_validation():
    v = Mock()
    v.errors = 1
    v.warnings = 1
    assert '1 error, 1 warning' == render(
        '{{ summarize_validation(validation) }}', {'validation': v}
    )
    v.errors = 2
    assert '2 errors, 1 warning' == render(
        '{{ summarize_validation(validation) }}', {'validation': v}
    )
    v.warnings = 2
    assert '2 errors, 2 warnings' == render(
        '{{ summarize_validation(validation) }}', {'validation': v}
    )


def test_log_action_class():
    v = Mock()
    for k, v in amo.LOG_BY_ID.items():
        if v.action_class is not None:
            cls = 'action-' + v.action_class
        else:
            cls = ''
        assert render('{{ log_action_class(id) }}', {'id': v.id}) == cls


@pytest.mark.parametrize(
    'action1,action2,action3,expected_count',
    (
        # Tests with Developer_Reply
        (
            LOG.REVIEWER_REPLY_VERSION,
            LOG.DEVELOPER_REPLY_VERSION,
            LOG.REVIEWER_REPLY_VERSION,
            1,
        ),
        (
            LOG.REVIEWER_REPLY_VERSION,
            LOG.REVIEWER_REPLY_VERSION,
            LOG.DEVELOPER_REPLY_VERSION,
            0,
        ),
        # Tests with Approval
        (
            LOG.APPROVE_VERSION,
            LOG.REVIEWER_REPLY_VERSION,
            LOG.REVIEWER_REPLY_VERSION,
            2,
        ),
        (
            LOG.REVIEWER_REPLY_VERSION,
            LOG.APPROVE_VERSION,
            LOG.REVIEWER_REPLY_VERSION,
            1,
        ),
        (
            LOG.REVIEWER_REPLY_VERSION,
            LOG.REVIEWER_REPLY_VERSION,
            LOG.APPROVE_VERSION,
            0,
        ),
        # Tests with Rejection
        (LOG.REJECT_VERSION, LOG.REVIEWER_REPLY_VERSION, LOG.REVIEWER_REPLY_VERSION, 2),
        (LOG.REVIEWER_REPLY_VERSION, LOG.REJECT_VERSION, LOG.REVIEWER_REPLY_VERSION, 1),
        (LOG.REVIEWER_REPLY_VERSION, LOG.REVIEWER_REPLY_VERSION, LOG.REJECT_VERSION, 0),
    ),
)
def test_pending_activity_log_count_for_developer(
    action1, action2, action3, expected_count
):
    user = user_factory()
    addon = addon_factory()
    version = addon.current_version
    ActivityLog.create(action1, addon, version, user=user).update(created=days_ago(2))
    ActivityLog.create(action2, addon, version, user=user).update(created=days_ago(1))
    ActivityLog.create(action3, addon, version, user=user).update(created=days_ago(0))

    count = jinja_helpers.pending_activity_log_count_for_developer(version)
    assert count == expected_count
