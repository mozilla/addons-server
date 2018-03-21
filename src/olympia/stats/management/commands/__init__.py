import boto3
import codecs
import json
import os
from datetime import datetime
from io import StringIO
from urlparse import urlparse

from django.core.files.base import ContentFile
from django.core.files.storage import get_storage_class
from django.forms.models import model_to_dict


storage = get_storage_class()()


IP_DENY_LIST = """
    -- Mozilla Network
    ip_address NOT LIKE '63.245.208.%' AND
    ip_address NOT LIKE '63.245.209.%' AND
    ip_address NOT LIKE '63.245.21%' AND
    ip_address NOT LIKE '63.245.220.%' AND
    ip_address NOT LIKE '63.245.221.%' AND
    ip_address NOT LIKE '63.245.222.%' AND
    ip_address NOT LIKE '63.245.223.%' AND

    -- Not sure, but grepped an hour of logs, nothing.
    ip_address NOT LIKE '180.92.184.%' AND

    -- CN adm
    ip_address NOT LIKE '59.151.50%' AND
    ip_address NOT IN (
        -- Not sure
        '72.26.221.66',
        '72.26.221.67',

        -- white hat
        '209.10.217.226',

        -- CN lbs
        '223.202.6.11',
        '223.202.6.12',
        '223.202.6.13',
        '223.202.6.14',
        '223.202.6.15',
        '223.202.6.16',
        '223.202.6.17',
        '223.202.6.18',
        '223.202.6.19',
        '223.202.6.20'
    )
"""


def get_date(path, sep):
    parsed = urlparse(path)

    if parsed.scheme == 's3':
        obj = get_object_from_s3(parsed.netloc, parsed.path,
                                 range='bytes=0-4096')
        line = obj.splitlines()[0]
    else:
        with open(path) as f:
            line = f.readline()

    try:
        return line.split(sep)[0]
    except IndexError:
        return None


def get_stats_data(path):
    parsed = urlparse(path)

    if parsed.scheme == 's3':
        return get_object_from_s3(parsed.netloc, parsed.path).splitlines(True)
    else:
        with codecs.open(parsed.path, encoding='utf8') as count_file:
            return StringIO(count_file.read())


def get_object_from_s3(bucket, object_key, range=''):
    """Get the ojbect from the s3"""

    client = boto3.client('s3')
    obj = client.get_object(Bucket=bucket, Key=object_key.lstrip('/'),
                            Range=range)
    return obj['Body'].read().decode('utf-8')


def serialize_stats(model):
    """Return the stats from the model ready to write to a file."""
    data = model_to_dict(model)
    del data['id']  # No need for the model's ID at all (eg: UpdateCount).
    return json.dumps(data)


def save_stats_to_file(model):
    """Save the given model to a file on the disc."""
    model_name = model._meta.model_name
    date = datetime.strptime(model.date, '%Y-%m-%d')
    path = u'{addon_id}/{date.year}/{date.month:02}/'.format(
        addon_id=model.addon_id, date=date)
    name_tpl = u'{date.year}_{date.month:02}_{date.day:02}_{model_name}.json'
    name = name_tpl.format(date=date, model_name=model_name)
    filepath = os.path.join(path, name)
    storage.save(filepath, ContentFile(serialize_stats(model)))
