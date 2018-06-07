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
            '<div id="trans-foo" class="trans" data-name="foo">'
            '<input lang="en-us" name="foo_en-us" type="text"'
            ' value="test value en" />'
            '<input lang="fr" name="foo_fr" type="text"'
            ' value="test value fr" />'
            '<input class="trans-init hidden" lang="init" name="foo_init" '
            'type="text" value="" /></div>')
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
            '<div id="trans-foo" class="trans" data-name="foo">'
            '<textarea cols="40" lang="en-us" name="foo_en-us" rows="10">\r\n'
            'test value en</textarea>'
            '<textarea cols="40" lang="fr" name="foo_fr" rows="10">\r\n'
            'test value fr</textarea>'
            '<textarea class="trans-init hidden" cols="40" lang="init" '
            'name="foo_init" rows="10">\r\n</textarea></div>')
        assert widget.render('foo', 666) == expected_output

    def test_value_from_datadict(self):
        data = {'f_en-US': 'woo', 'f_de': 'herr', 'f_fr_delete': ''}
        actual = widgets.TransInput().value_from_datadict(data, [], 'f')
        expected = {'en-US': 'woo', 'de': 'herr', 'fr': None}
        assert actual == expected
