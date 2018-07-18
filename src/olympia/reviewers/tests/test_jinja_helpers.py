# -*- coding: utf-8 -*-
import pytest

from mock import Mock

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase
from olympia.files.models import File
from olympia.reviewers.templatetags import jinja_helpers
from olympia.translations.models import Translation
from olympia.versions.models import Version


pytestmark = pytest.mark.django_db


def test_page_title_unicode():
    t = Translation(localized_string=u'\u30de\u30eb\u30c1\u30d712\u30eb')
    request = Mock()
    request.APP = amo.FIREFOX
    jinja_helpers.reviewer_page_title({'request': request}, title=t)


class TestCompareLink(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestCompareLink, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.current = File.objects.get(pk=67442)
        self.version = Version.objects.create(addon=self.addon)

    def test_same_platform(self):
        file = File.objects.create(
            version=self.version, platform=self.current.platform
        )
        assert (
            file.pk
            == jinja_helpers.file_compare(self.current, self.version).pk
        )

    def test_different_platform(self):
        file = File.objects.create(
            version=self.version, platform=self.current.platform
        )
        File.objects.create(
            version=self.version, platform=amo.PLATFORM_LINUX.id
        )
        assert (
            file.pk
            == jinja_helpers.file_compare(self.current, self.version).pk
        )

    def test_specific_platform(self):
        self.current.platform_id = amo.PLATFORM_LINUX.id
        self.current.save()

        linux = File.objects.create(
            version=self.version, platform=amo.PLATFORM_LINUX.id
        )
        assert (
            linux.pk
            == jinja_helpers.file_compare(self.current, self.version).pk
        )

    def test_no_platform(self):
        self.current.platform_id = amo.PLATFORM_LINUX.id
        self.current.save()
        file = File.objects.create(
            version=self.version, platform=amo.PLATFORM_WIN.id
        )
        assert (
            file.pk
            == jinja_helpers.file_compare(self.current, self.version).pk
        )


def test_version_status():
    addon = Addon()
    version = Version()
    version.all_files = [
        File(status=amo.STATUS_PUBLIC),
        File(status=amo.STATUS_AWAITING_REVIEW),
    ]
    assert u'Approved,Awaiting Review' == (
        jinja_helpers.version_status(addon, version)
    )

    version.all_files = [File(status=amo.STATUS_AWAITING_REVIEW)]
    assert u'Awaiting Review' == jinja_helpers.version_status(addon, version)


def test_file_review_status_handles_invalid_status_id():
    # When status is a valid one, one of STATUS_CHOICES_FILE return label.
    assert amo.STATUS_CHOICES_FILE[amo.STATUS_PUBLIC] == (
        jinja_helpers.file_review_status(None, File(status=amo.STATUS_PUBLIC))
    )

    # 99 isn't a valid status, so return the status code for reference.
    status = jinja_helpers.file_review_status(None, File(status=99))
    assert u'[status:99]' == status
