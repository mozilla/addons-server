import boto3
import codecs
from io import StringIO
from urlparse import urlparse

from django.core.files.storage import get_storage_class


storage = get_storage_class()()


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
