from pyquery import PyQuery as pq

from olympia.amo.tests import TestCase
from olympia.translations import models, widgets


class TestWidget(TestCase):

    def test_avoid_purified_translation(self):
        # Even if we pass in a LinkifiedTranslation the widget switches to a
        # normal Translation before rendering.
        w = widgets.TransTextarea.widget()
        link = models.LinkifiedTranslation(localized_string='<b>yum yum</b>',
                                           locale='fr', id=10)
        link.clean()
        widget = w.render('name', link)
        assert pq(widget).html().strip() == '<b>yum yum</b>'

    def test_default_locale(self):
        w = widgets.TransTextarea()
        result = w.render('name', '')
        assert pq(result)('textarea:not([lang=init])').attr('lang') == 'en-us'

        w.default_locale = 'pl'
        result = w.render('name', '')
        assert pq(result)('textarea:not([lang=init])').attr('lang') == 'pl'

    def test_transinput(self):
        models.Translation.objects.create(
            id=666, locale='en-us', localized_string='test value en')
        models.Translation.objects.create(
            id=666, locale='fr', localized_string='test value fr')
        models.Translation.objects.create(
            id=666, locale='de', localized_string=None)

        widget = widgets.TransInput()
        assert not widget.is_hidden
        expected_output = (
            '<div id="trans-foo" class="trans" data-name="foo"><input '
            'type="text" name="foo_en-us" value="test value en" lang="en-us" '
            '/><input type="text" name="foo_fr" value="test value fr" '
            'lang="fr" /><input type="text" name="foo_init" value="" '
            'lang="init" class="trans-init hidden" /></div>')
        assert widget.render('foo', 666) == expected_output

    def test_transtextarea(self):
        models.Translation.objects.create(
            id=666, locale='en-us', localized_string='test value en')
        models.Translation.objects.create(
            id=666, locale='fr', localized_string='test value fr')
        models.Translation.objects.create(
            id=666, locale='de', localized_string=None)

        widget = widgets.TransTextarea()
        assert not widget.is_hidden
        expected_output = (
            '<div id="trans-foo" class="trans" data-name="foo"><textarea '
            'name="foo_en-us" lang="en-us" rows="10" cols="40">\ntest value en'
            '</textarea><textarea name="foo_fr" lang="fr" rows="10" cols="40">'
            '\ntest value fr</textarea><textarea name="foo_init" lang="init" '
            'rows="10" cols="40" class="trans-init hidden">\n</textarea>'
            '</div>')

        assert widget.render('foo', 666) == expected_output

    def test_value_from_datadict(self):
        data = {'f_en-US': 'woo', 'f_de': 'herr', 'f_fr_delete': ''}
        actual = widgets.TransInput().value_from_datadict(data, [], 'f')
        expected = {'en-US': 'woo', 'de': 'herr', 'fr': None}
        assert actual == expected
