from pyquery import PyQuery as pq
from nose.tools import eq_

import amo.tests
from translations import models, widgets


class TestWidget(amo.tests.TestCase):

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
