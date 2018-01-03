from django.conf import settings
from django.db import models
from django.utils import importlib

import MySQLdb as mysql

from pyquery import PyQuery as pq

from olympia.addons.models import Addon
from olympia.amo.tests import TestCase


def pubdir(ob):
    for name in dir(ob):
        if not name.startswith('_'):
            yield name


def quickcopy(val):
    if isinstance(val, dict):
        val = val.copy()
    elif isinstance(val, list):
        val = list(val)
    return val


class ReadOnlyModeTest(TestCase):
    extra = ('olympia.amo.middleware.ReadOnlyMiddleware',)

    def setUp(self):
        super(ReadOnlyModeTest, self).setUp()
        models.signals.pre_save.connect(self.db_error)
        models.signals.pre_delete.connect(self.db_error)
        self.old_settings = dict((k, quickcopy(getattr(settings, k)))
                                 for k in pubdir(settings))
        settings.SLAVE_DATABASES = ['default']
        settings_module = importlib.import_module(settings.SETTINGS_MODULE)
        settings_module.read_only_mode(settings._wrapped.__dict__)
        self.client.handler.load_middleware()

    def tearDown(self):
        for k in pubdir(settings):
            if k not in self.old_settings:
                delattr(self.old_settings, k)
        for k, v in self.old_settings.items():
            try:
                setattr(settings, k, v)
            except AttributeError:
                # __weakref__
                pass
        models.signals.pre_save.disconnect(self.db_error)
        models.signals.pre_delete.disconnect(self.db_error)
        super(ReadOnlyModeTest, self).tearDown()

    def db_error(self, *args, **kwargs):
        raise mysql.OperationalError("You can't do this in read-only mode.")

    def test_db_error(self):
        self.assertRaises(mysql.OperationalError, Addon.objects.create, id=12)

    def test_bail_on_post(self):
        r = self.client.post('/en-US/firefox/')
        assert r.status_code == 503
        title = pq(r.content)('title').text()
        assert title.startswith('Maintenance in progress'), title
