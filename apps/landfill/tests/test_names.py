# -*- coding: utf-8 -*-
from nose.tools import ok_

import amo
import amo.tests
from landfill.names import generate_names


class NamesTests(amo.tests.TestCase):

    def test_names_generation(self):
        assert len(generate_names()) == 136
        ok_('Exquisite Sandwich' in generate_names())
