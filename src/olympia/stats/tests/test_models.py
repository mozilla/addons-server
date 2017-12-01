# -*- coding: utf-8 -*-
import json

from olympia.amo.tests import TestCase
from olympia.stats.db import StatsDictField


class TestStatsDictField(TestCase):

    def test_to_python_none(self):
        assert StatsDictField().to_python(None) is None

    def test_to_python_dict(self):
        assert StatsDictField().to_python({'a': 1}) == {'a': 1}

    def test_to_python_json(self):
        val = {'a': 1}
        assert StatsDictField().to_python(json.dumps(val)) == val
