from nose.tools import eq_

from amo.tests import app_factory


class DynamicBoolFieldsTestMixin():

    def setUp(self):
        """
        Create an instance of the DynamicBoolFields model and call super
        on the inheriting setUp.
        (e.g. RatingDescriptors.objects.create(addon=self.app))
        """
        self.app = app_factory()
        self.model = None
        self.related_name = ''  # Related name of the bool table on the Webapp.

        self.BOOL_DICT = []
        self.flags = []  # Flag names.
        self.expected = []  # Translation names.

    def _get_related_bool_obj(self):
        return getattr(self.app, self.related_name)

    def _flag(self):
        """Flag app with a handful of flags for testing."""
        self._get_related_bool_obj().update(
            **dict(('has_%s' % f.lower(), True) for f in self.flags))

    def _check(self, obj=None):
        if not obj:
            obj = self._get_related_bool_obj()

        for bool_name in self.BOOL_DICT:
            field = 'has_%s' % bool_name.lower()
            value = bool_name in self.flags
            if isinstance(obj, dict):
                eq_(obj[field], value,
                    u'Unexpected value for field: %s' % field)
            else:
                eq_(getattr(obj, field), value,
                    u'Unexpected value for field: %s' % field)

    def to_unicode(self, items):
        """
        Force unicode evaluation of lazy items in the passed list, for set
        comparison to a list of already-evaluated unicode strings.
        """
        return [unicode(i) for i in items]

    def test_bools_set(self):
        self._flag()
        self._check()

    def test_bools_unset(self):
        eq_(self._get_related_bool_obj().to_list(), [])

    def test_to_dict(self):
        self._flag()
        self._check(self._get_related_bool_obj().to_dict())

    def test_to_list(self):
        self._flag()
        to_list = self._get_related_bool_obj().to_list()
        self.assertSetEqual(self.to_unicode(to_list), self.expected)

    def test_default_false(self):
        obj = self.model(addon=self.app)
        eq_(getattr(obj, 'has_%s' % self.flags[0].lower()), False)
