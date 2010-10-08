import copy

from django.conf import settings
from django.db import models
from django.utils import importlib

import MySQLdb as mysql
import test_utils
import safe_signals
from nose.tools import assert_raises, eq_
from pyquery import PyQuery as pq

from amo.urlresolvers import reverse
from addons.models import Addon


class ReadOnlyModeTest(test_utils.TestCase):
    extra = ('amo.middleware.ReadOnlyMiddleware',)

    def setUp(self):
        safe_signals.Signal.send = safe_signals.unsafe_send
        models.signals.pre_save.connect(self.db_error)
        models.signals.pre_delete.connect(self.db_error)
        self.old_settings = copy.deepcopy(settings._wrapped.__dict__)
        settings.SLAVE_DATABASES = ['default']
        settings_module = importlib.import_module(settings.SETTINGS_MODULE)
        settings_module.read_only_mode(settings._wrapped.__dict__)
        self.client.handler.load_middleware()

    def tearDown(self):
        settings._wrapped.__dict__ = self.old_settings
        models.signals.pre_save.disconnect(self.db_error)
        models.signals.pre_delete.disconnect(self.db_error)
        safe_signals.Signal.send = safe_signals.safe_send

    def db_error(self, *args, **kwargs):
        raise mysql.OperationalError("You can't do this in read-only mode.")

    def test_db_error(self):
        assert_raises(mysql.OperationalError, Addon.objects.create, id=12)

    def test_login_error(self):
        # This tries to do a db write.
        r = self.client.get(reverse('users.login'))
        eq_(r.status_code, 503)
        title = pq(r.content)('title').text()
        assert title.startswith('Maintenance in progress'), title

    def test_bail_on_post(self):
        r = self.client.post('/en-US/firefox/')
        eq_(r.status_code, 503)
        title = pq(r.content)('title').text()
        assert title.startswith('Maintenance in progress'), title
