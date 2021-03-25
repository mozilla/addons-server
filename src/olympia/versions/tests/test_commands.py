from django.core.management import call_command

import pytest

from olympia.amo.tests import addon_factory, version_factory
from olympia.versions.models import Version


@pytest.mark.django_db
def test_hard_delete_versions_without_files():
    addon = addon_factory()
    version_with_files = addon.current_version
    version_without_files = version_factory(addon=addon)
    version_without_files.files.all().delete()
    assert Version.unfiltered.count() == 2

    call_command('process_versions', task='delete_versions_without_files')

    assert Version.unfiltered.count() == 1
    assert Version.unfiltered.filter(pk=version_with_files.pk).exists()
    assert not Version.unfiltered.filter(pk=version_without_files.pk).exists()
