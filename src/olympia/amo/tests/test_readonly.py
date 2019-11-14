from django.db import models

import MySQLdb as mysql
import pytest

from pyquery import PyQuery as pq

from olympia.addons.models import Addon
from olympia.amo.tests import reverse_ns


@pytest.yield_fixture
def read_only_mode(client, settings, db):
    def _db_error(*args, **kwargs):
        raise mysql.OperationalError("You can't do this in read-only mode.")

    settings.REPLICA_DATABASES = ['default']
    models.signals.pre_save.connect(_db_error)
    models.signals.pre_delete.connect(_db_error)

    from olympia.lib.settings_base import read_only_mode

    env = {
        'REPLICA_DATABASES': settings.REPLICA_DATABASES,
        'DATABASES': settings.DATABASES,
    }

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
    response = client.post('/en-US/developers/')
    assert response.status_code == 503
    title = pq(response.content)('title').text()
    assert title.startswith('Maintenance in progress'), title


@pytest.mark.parametrize('method', ('post', 'put', 'delete', 'patch'))
def test_api_bail_on_write_method(read_only_mode, client, method):
    response = getattr(client, method)(reverse_ns('abusereportuser-list'))

    assert response.status_code == 503
    assert 'website maintenance' in response.json()['error']
