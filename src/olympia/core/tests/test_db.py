# -*- coding: utf-8 -*-
import pytest

from olympia.core.tests.db_tests_testapp.models import TestRegularCharField


@pytest.mark.django_db
@pytest.mark.parametrize(
    'value',
    [
        'a',
        '🔍',  # Magnifying Glass Tilted Left (U+1F50D)
        '❤',  # Heavy Black Heart (U+2764, U+FE0F)
    ],
)
def test_max_length_utf8mb4(value):
    TestRegularCharField.objects.create(name=value * 255)

    assert TestRegularCharField.objects.get().name == value * 255
