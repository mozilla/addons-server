# -*- coding: utf-8 -*-
import urllib

from django.utils import translation

import pytest

from mock import Mock

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon
from olympia.amo import LOG
from olympia.amo.tests import TestCase, addon_factory, days_ago, user_factory
from olympia.amo.tests.test_helpers import render
from olympia.devhub.templatetags import jinja_helpers
from olympia.files.models import File
from olympia.versions.models import Version


pytestmark = pytest.mark.django_db


def test_dev_page_title():
    translation.activate('en-US')
    request = Mock()
    request.APP = None
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
    s2 = render('{{ page_title("%s :: %s") }}' % (title, addon.name), ctx)
    assert s1 == s2


def test_summarize_validation():
    v = Mock()
    v.errors = 1
    v.warnings = 1
    assert u'1 error, 1 warning' == render(
        '{{ summarize_validation(validation) }}', {'validation': v}
    )
    v.errors = 2
    assert u'2 errors, 1 warning' == render(
        '{{ summarize_validation(validation) }}', {'validation': v}
    )
    v.warnings = 2
    assert u'2 errors, 2 warnings' == render(
        '{{ summarize_validation(validation) }}', {'validation': v}
    )


def test_log_action_class():
    v = Mock()
    for k, v in amo.LOG_BY_ID.iteritems():
        if v.action_class is not None:
            cls = 'action-' + v.action_class
        else:
            cls = ''
        assert render('{{ log_action_class(id) }}', {'id': v.id}) == cls


class TestDisplayUrl(amo.tests.BaseTestCase):
    def setUp(self):
        super(TestDisplayUrl, self).setUp()
        self.raw_url = u'http://host/%s' % 'フォクすけといっしょ'.decode('utf8')

    def test_utf8(self):
        url = urllib.quote(self.raw_url.encode('utf8'))
        assert render('{{ url|display_url }}', {'url': url}) == (self.raw_url)

    def test_unicode(self):
        url = urllib.quote(self.raw_url.encode('utf8'))
        url = unicode(url, 'utf8')
        assert render('{{ url|display_url }}', {'url': url}) == (self.raw_url)


class TestDevFilesStatus(TestCase):
    def setUp(self):
        super(TestDevFilesStatus, self).setUp()
        self.addon = Addon.objects.create(type=1, status=amo.STATUS_NOMINATED)
        self.version = Version.objects.create(addon=self.addon)
        self.file = File.objects.create(
            version=self.version,
            platform=amo.PLATFORM_ALL.id,
            status=amo.STATUS_AWAITING_REVIEW,
        )

    def expect(self, expected):
        cnt, msg = jinja_helpers.dev_files_status([self.file])[0]
        assert cnt == 1
        assert msg == unicode(expected)

    def test_unreviewed_public(self):
        self.addon.status = amo.STATUS_PUBLIC
        self.file.status = amo.STATUS_AWAITING_REVIEW
        self.expect(File.STATUS_CHOICES[amo.STATUS_AWAITING_REVIEW])

    def test_unreviewed_nominated(self):
        self.addon.status = amo.STATUS_NOMINATED
        self.file.status = amo.STATUS_AWAITING_REVIEW
        self.expect(File.STATUS_CHOICES[amo.STATUS_AWAITING_REVIEW])

    def test_reviewed_public(self):
        self.addon.status = amo.STATUS_PUBLIC
        self.file.status = amo.STATUS_PUBLIC
        self.expect(File.STATUS_CHOICES[amo.STATUS_PUBLIC])

    def test_reviewed_null(self):
        self.addon.status = amo.STATUS_NULL
        self.file.status = amo.STATUS_AWAITING_REVIEW
        self.expect(File.STATUS_CHOICES[amo.STATUS_AWAITING_REVIEW])

    def test_disabled(self):
        self.addon.status = amo.STATUS_PUBLIC
        self.file.status = amo.STATUS_DISABLED
        self.expect(File.STATUS_CHOICES[amo.STATUS_DISABLED])


@pytest.mark.parametrize(
    'action1,action2,action3,expected_count',
    (
        (
            LOG.REQUEST_INFORMATION,
            LOG.REQUEST_INFORMATION,
            LOG.REQUEST_INFORMATION,
            3,
        ),
        # Tests with Developer_Reply
        (
            LOG.DEVELOPER_REPLY_VERSION,
            LOG.REQUEST_INFORMATION,
            LOG.REQUEST_INFORMATION,
            2,
        ),
        (
            LOG.REQUEST_INFORMATION,
            LOG.DEVELOPER_REPLY_VERSION,
            LOG.REQUEST_INFORMATION,
            1,
        ),
        (
            LOG.REQUEST_INFORMATION,
            LOG.REQUEST_INFORMATION,
            LOG.DEVELOPER_REPLY_VERSION,
            0,
        ),
        # Tests with Approval
        (
            LOG.APPROVE_VERSION,
            LOG.REQUEST_INFORMATION,
            LOG.REQUEST_INFORMATION,
            2,
        ),
        (
            LOG.REQUEST_INFORMATION,
            LOG.APPROVE_VERSION,
            LOG.REQUEST_INFORMATION,
            1,
        ),
        (
            LOG.REQUEST_INFORMATION,
            LOG.REQUEST_INFORMATION,
            LOG.APPROVE_VERSION,
            0,
        ),
        # Tests with Rejection
        (
            LOG.REJECT_VERSION,
            LOG.REQUEST_INFORMATION,
            LOG.REQUEST_INFORMATION,
            2,
        ),
        (
            LOG.REQUEST_INFORMATION,
            LOG.REJECT_VERSION,
            LOG.REQUEST_INFORMATION,
            1,
        ),
        (
            LOG.REQUEST_INFORMATION,
            LOG.REQUEST_INFORMATION,
            LOG.REJECT_VERSION,
            0,
        ),
    ),
)
def test_pending_activity_log_count_for_developer(
    action1, action2, action3, expected_count
):
    user = user_factory()
    addon = addon_factory()
    version = addon.current_version
    ActivityLog.create(action1, addon, version, user=user).update(
        created=days_ago(2)
    )
    ActivityLog.create(action2, addon, version, user=user).update(
        created=days_ago(1)
    )
    ActivityLog.create(action3, addon, version, user=user).update(
        created=days_ago(0)
    )

    count = jinja_helpers.pending_activity_log_count_for_developer(version)
    assert count == expected_count
