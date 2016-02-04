from pyquery import PyQuery as pq
from nose.tools import eq_

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
        eq_(pq(widget).html().strip(), '<b>yum yum</b>')

    def test_default_locale(self):
        w = widgets.TransTextarea()
        result = w.render('name', '')
        eq_(pq(result)('textarea:not([lang=init])').attr('lang'), 'en-us')

        w.default_locale = 'pl'
        result = w.render('name', '')
        eq_(pq(result)('textarea:not([lang=init])').attr('lang'), 'pl')
