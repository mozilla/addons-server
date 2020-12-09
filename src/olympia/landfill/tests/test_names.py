# -*- coding: utf-8 -*-
from olympia.amo.tests import TestCase
from olympia.landfill.names import generate_names


class NamesTests(TestCase):
    def test_names_generation(self):
        assert len(generate_names()) == 136
        assert 'Exquisite Sandwich' in generate_names()
