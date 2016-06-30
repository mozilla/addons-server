import json
import os
from datetime import datetime

from django.core.files.base import ContentFile
from django.core.files.storage import get_storage_class
from django.forms.models import model_to_dict


storage = get_storage_class()()


IP_BLACKLIST = """
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


def get_date_from_file(filepath, sep):
    """Get the date from the file, which should be the first col."""
    with open(filepath) as f:
        line = f.readline()
        try:
            return line.split(sep)[0]
        except IndexError:
            return None


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
