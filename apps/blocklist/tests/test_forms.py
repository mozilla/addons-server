from amo.tests import TestCase
from blocklist import forms
from blocklist.models import BlocklistItem, BlocklistPlugin


class BlocklistFormTest(TestCase):

    def setUp(self):
        super(BlocklistFormTest, self).setUp()
        self.blitem = BlocklistItem.objects.create()
        self.blplugin = BlocklistPlugin.objects.create()

    def test_app_form_only_blitem(self):
        data = {'blitem': self.blitem.pk, 'blplugin': None}
        form = forms.BlocklistAppForm(data)
        assert form.is_valid()

    def test_app_form_only_blplugin(self):
        data = {'blplugin': self.blplugin.pk, 'blitem': None}
        form = forms.BlocklistAppForm(data)
        assert form.is_valid()

    def test_app_form_neither_blplugin_and_blitem(self):
        data = {'blitem': None, 'blplugin': None}
        form = forms.BlocklistAppForm(data)
        assert not form.is_valid()
        assert 'One and only one' in str(form.errors)

    def test_app_form_both_blplugin_and_blitem(self):
        data = {'blitem': self.blitem.pk, 'blplugin': self.blplugin.pk}
        form = forms.BlocklistAppForm(data)
        assert not form.is_valid()
        assert 'One and only one' in str(form.errors)
