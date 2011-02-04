import unittest

import test_utils
from mock import Mock
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
from amo.tests.test_helpers import render
from discovery import helpers


def test_disco_pane_link():
    s = render('{{ disco_pane_link("discovery-pane-details") }}')
    doc = pq(s)
    back = doc('p.back a')
    eq_(back.text(), 'Back to Add-ons')
    eq_(back.attr('data-history'), '-1')

    s = render('{{ disco_pane_link("discovery-pane-eula") }}')
    doc = pq(s)
    eq_(doc('p.back a').attr('data-history'), '-2')
