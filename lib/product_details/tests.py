# -*- coding: utf-8 -*-
from nose.tools import eq_

import product_details


def test_spotcheck():
    """Check a couple product-details files to make sure they're available."""
    languages = product_details.languages
    eq_(languages['el']['English'], 'Greek')
    eq_(languages['el']['native'], u'Ελληνικά')

    eq_(product_details.firefox_history_major_releases['1.0'], '2004-11-09')
