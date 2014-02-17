# -*- coding: utf-8 -*-

from django.test import TestCase

from lib.template_loader import Loader


class TestLoader(TestCase):

    def test_valid_template(self):
        loader = Loader()

        with self.settings(JINGO_EXCLUDE_PATHS=[], JINGO_EXCLUDE_APPS=[]):
            assert loader._valid_template('foo')  # No JINGO_EXCLUDE_*.

        with self.settings(JINGO_EXCLUDE_PATHS=[],
                           JINGO_EXCLUDE_APPS=['foo', 'bar/baz']):
            assert not loader._valid_template('foo')  # Excluded by jingo.
            assert not loader._valid_template('foo/bar')
            # This is valid, and shouldn't, and that's why we have our own
            # loader which uses JINGO_EXCLUDE_PATHS.
            assert loader._valid_template('bar/baz')

        with self.settings(JINGO_EXCLUDE_PATHS=['foo/bar'],
                           JINGO_EXCLUDE_APPS=[]):
            assert loader._valid_template('foo')
            assert not loader._valid_template('foo/bar')
            assert not loader._valid_template('foo/bar/baz')
