from django.db import models

import MySQLdb as mysql
import pytest

from pyquery import PyQuery as pq

from olympia.addons.models import Addon


@pytest.yield_fixture
def read_only_mode(client, settings, db):
    def _db_error(*args, **kwargs):
        raise mysql.OperationalError("You can't do this in read-only mode.")

    settings.SLAVE_DATABASES = ['default']
    models.signals.pre_save.connect(_db_error)
    models.signals.pre_delete.connect(_db_error)

    from olympia.lib.settings_base import read_only_mode

    env = {key: getattr(settings, key) for key in settings._explicit_settings}

    read_only_mode(env)

    for key, value in env.items():
        setattr(settings, key, value)

    client.handler.load_middleware()

    yield

    models.signals.pre_save.disconnect(_db_error)
    models.signals.pre_delete.disconnect(_db_error)


def test_db_error(read_only_mode):
    with pytest.raises(mysql.OperationalError):
        Addon.objects.create(id=12)


def test_bail_on_post(read_only_mode, client):
    r = client.post('/en-US/firefox/')
    assert r.status_code == 503
    title = pq(r.content)('title').text()
    assert title.startswith('Maintenance in progress'), title
