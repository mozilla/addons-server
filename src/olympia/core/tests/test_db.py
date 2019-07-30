# -*- coding: utf-8 -*-
import os
import pytest

from olympia.core.tests.db_tests_testapp.models import TestRegularCharField


@pytest.mark.django_db
@pytest.mark.parametrize('value', [
    u'a',
    u'🔍',  # Magnifying Glass Tilted Left (U+1F50D)
    u'❤',  # Heavy Black Heart (U+2764, U+FE0F)
])
def test_max_length_utf8mb4(value):
    TestRegularCharField.objects.create(name=value * 255)

    assert TestRegularCharField.objects.get().name == value * 255


def test_no_duplicate_migration_ids():
    seen = set()

    migration_ids = [
        fname.split('-')[0] for fname in os.listdir('src/olympia/migrations/')
        if fname.endswith('.sql')]

    duplicates = {x for x in migration_ids if x in seen or seen.add(x)}

    assert not duplicates
