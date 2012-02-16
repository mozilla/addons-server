from nose.tools import eq_

import amo.tests
from addons.models import Addon
from mkt.developers.tasks import convert_purified


class TestPurify(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)

    def test_no_html(self):
        self.addon.the_reason = 'foo'
        self.addon.save()
        last = Addon.objects.get(pk=3615).modified
        convert_purified([self.addon.pk])
        addon = Addon.objects.get(pk=3615)
        eq_(addon.modified, last)

    def test_has_html(self):
        self.addon.the_reason = 'foo <script>foo</script>'
        self.addon.save()
        convert_purified([self.addon.pk])
        addon = Addon.objects.get(pk=3615)
        assert addon.the_reason.localized_string_clean
