# -*- coding: utf-8 -*-
import pytest

from django.test.utils import override_settings

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase
from olympia.files.models import File
from olympia.reviewers.templatetags import jinja_helpers
from olympia.versions.models import Version


pytestmark = pytest.mark.django_db


class TestCompareLink(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestCompareLink, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.current = File.objects.get(pk=67442)
        self.version = Version.objects.create(addon=self.addon)

    def test_same_platform(self):
        file = File.objects.create(version=self.version,
                                   platform=self.current.platform)
        assert file.pk == jinja_helpers.file_compare(
            self.current, self.version).pk

    def test_different_platform(self):
        file = File.objects.create(version=self.version,
                                   platform=self.current.platform)
        File.objects.create(version=self.version,
                            platform=amo.PLATFORM_LINUX.id)
        assert file.pk == jinja_helpers.file_compare(
            self.current, self.version).pk

    def test_specific_platform(self):
        self.current.platform_id = amo.PLATFORM_LINUX.id
        self.current.save()

        linux = File.objects.create(version=self.version,
                                    platform=amo.PLATFORM_LINUX.id)
        assert linux.pk == jinja_helpers.file_compare(
            self.current, self.version).pk

    def test_no_platform(self):
        self.current.platform_id = amo.PLATFORM_LINUX.id
        self.current.save()
        file = File.objects.create(version=self.version,
                                   platform=amo.PLATFORM_WIN.id)
        assert file.pk == jinja_helpers.file_compare(
            self.current, self.version).pk


def test_version_status():
    addon = Addon()
    version = Version()
    version.all_files = [File(status=amo.STATUS_APPROVED),
                         File(status=amo.STATUS_AWAITING_REVIEW)]
    assert u'Approved,Awaiting Review' == (
        jinja_helpers.version_status(addon, version))

    version.all_files = [File(status=amo.STATUS_AWAITING_REVIEW)]
    assert u'Awaiting Review' == jinja_helpers.version_status(addon, version)


def test_file_review_status_handles_invalid_status_id():
    # When status is a valid one, one of STATUS_CHOICES_FILE return label.
    assert amo.STATUS_CHOICES_FILE[amo.STATUS_APPROVED] == (
        jinja_helpers.file_review_status(
            None, File(status=amo.STATUS_APPROVED)))

    # 99 isn't a valid status, so return the status code for reference.
    status = jinja_helpers.file_review_status(None, File(status=99))
    assert u'[status:99]' == status


def test_create_a_code_manager_url():
    with override_settings(CODE_MANAGER_URL='http://code-manager'):
        assert jinja_helpers.code_manager_url('/some/path') == (
            'http://code-manager/en-US/some/path'
        )


def test_code_manager_url_expects_a_relative_path():
    with pytest.raises(ValueError):
        jinja_helpers.code_manager_url('http://code-manager/some/path')
