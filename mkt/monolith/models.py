import datetime
import hashlib
import json

from django.db import models


class MonolithRecord(models.Model):
    """Data stored temporarily for monolith.

    It contains a key (e.g. "app.install"), the date of the record, a user (a
    string representing a unique user) and a value (which internally is stored
    as a JSON object).
    """
    key = models.CharField(max_length=255)
    recorded = models.DateTimeField()
    user_hash = models.CharField(max_length=255)
    value = models.TextField()

    class Meta:
        db_table = 'monolith_record'


def get_user_hash(request):
    """Get a hash identifying an user.

    It's a hash of session key, ip and user agent
    """
    ip = request.META.get('REMOTE_ADDR', '')
    ua = request.META.get('User-Agent', '')
    session_key = request.session.session_key or ''

    return hashlib.sha1('-'.join((ip, ua, str(session_key)))).hexdigest()


def record_stat(key, request, recorded=None, **data):
    """Create a new record in the database with the given values.

    :param key:
        The type of stats you're sending, e.g. "app.install".

    :param request:
        The request associated with this call. It will be used to define who
        the user is.

    :param recorded:
        The date for the record insertion. By default, uses "now".

    :para: data:
        The data you want to store. You can pass the data to this function as
        named arguments.
    """
    if recorded is None:
        recorded = datetime.datetime.now()

    if not data:
        raise ValueError('You should at least define one value')

    record = MonolithRecord(key=key, user_hash=get_user_hash(request),
                            recorded=recorded, value=json.dumps(data))
    record.save()
    return record
