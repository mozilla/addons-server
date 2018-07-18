# -*- coding: utf-8 -*-
import pytest

from olympia.search.utils import floor_version


pytestmark = pytest.mark.django_db


def test_floor_version():
    def c(x, y):
        assert floor_version(x) == y

    c(None, None)
    c('', '')
    c('3', '3.0')
    c('3.6', '3.6')
    c('3.6.22', '3.6')
    c('5.0a2', '5.0')
    c('8.0', '8.0')
    c('8.0.10a', '8.0')
    c('10.0b2pre', '10.0')
    c('8.*', '8.0')
    c('8.0*', '8.0')
    c('8.0.*', '8.0')
    c('8.x', '8.0')
    c('8.0x', '8.0')
    c('8.0.x', '8.0')
    c(u'acux5442À¾z1À¼z2abcxuca5442', u'acux5442À¾z1À¼z2abcxuca5442')
