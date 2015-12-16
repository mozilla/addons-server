# -*- coding: utf-8 -*-
from nose.tools import eq_, ok_

from olympia.amo.tests import TestCase
from olympia.landfill.names import generate_names


class NamesTests(TestCase):

    def test_names_generation(self):
        eq_(len(generate_names()), 136)
        ok_('Exquisite Sandwich' in generate_names())
