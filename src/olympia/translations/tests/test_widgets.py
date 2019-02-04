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

        doc = pq(widget.render('foo', 666))

        assert doc.attr('id') == 'trans-foo'
        assert doc.attr('class') == 'trans'
        assert doc.attr('data-name') == 'foo'
        assert len(doc('input')) == 3
        assert doc('input')[0].get('lang') == 'en-us'
        assert doc('input')[0].get('name') == 'foo_en-us'

        assert doc('input')[1].get('lang') == 'fr'
        assert doc('input')[1].get('name') == 'foo_fr'

        assert doc('input')[2].get('lang') == 'init'
        assert doc('input')[2].get('name') == 'foo_init'

    def test_transtextarea(self):
        models.Translation.objects.create(
            id=666, locale='en-us', localized_string='test value en')
        models.Translation.objects.create(
            id=666, locale='fr', localized_string='test value fr')
        models.Translation.objects.create(
            id=666, locale='de', localized_string=None)

        widget = widgets.TransTextarea()
        assert not widget.is_hidden

        doc = pq(widget.render('foo', 666))

        assert doc.attr('id') == 'trans-foo'
        assert doc.attr('class') == 'trans'
        assert doc.attr('data-name') == 'foo'
        assert len(doc('textarea')) == 3
        assert doc('textarea')[0].get('lang') == 'en-us'
        assert doc('textarea')[0].get('name') == 'foo_en-us'

        assert doc('textarea')[1].get('lang') == 'fr'
        assert doc('textarea')[1].get('name') == 'foo_fr'

        assert doc('textarea')[2].get('lang') == 'init'
        assert doc('textarea')[2].get('name') == 'foo_init'

    def test_value_from_datadict(self):
        data = {'f_en-US': 'woo', 'f_de': 'herr', 'f_fr_delete': ''}
        actual = widgets.TransInput().value_from_datadict(data, [], 'f')
        expected = {'en-US': 'woo', 'de': 'herr', 'fr': None}
        assert actual == expected
