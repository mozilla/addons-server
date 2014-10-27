# flake8: noqa
from . import HiveQueryToFileCommand


class Command(HiveQueryToFileCommand):
    """Query the "update counts by version" requests from HIVE, save to disk.

    The data stored locally will then be processed by the
    update_counts_from_file.py script.

    Usage:
    ./manage.py update_counts_by_version_from_hive --date YYYY-MM-DD

    If no date is specified, the default is the day before.
    If not folder is specified, the default is "hive_results". This folder is
    located in <settings.NETAPP_STORAGE>/tmp.

    Example row:

    2014-07-01	0-2xz@rh-qurtqz-.co.uk	1.0	1	112

    """
    help = __doc__
    filename = 'update_counts_by_version.hive'
    query = """
        SELECT ds,
               COALESCE(REFLECT('java.net.URLDecoder', 'decode', PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'id')), PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'id')) AS ID,
               CASE COALESCE(REFLECT('java.net.URLDecoder', 'decode', COALESCE(PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'version'),'Invalid')), COALESCE(PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'version'),'Invalid'))
                   WHEN '%ITEM_VERSION%' THEN 'Invalid'
                   WHEN '' THEN 'Invalid'
                   WHEN NULL THEN 'Invalid'
                   ELSE COALESCE(REFLECT('java.net.URLDecoder', 'decode', COALESCE(PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'version'),'Invalid')), COALESCE(PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'version'), 'Invalid'))
               END AS VERSION,
               COUNT(*),
               PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'updateType')
        FROM V2_RAW_LOGS
        WHERE
            TRUE AND
            DOMAIN = 'versioncheck.addons.mozilla.org' AND
            DS = '{day}' AND
            {ip_filtering}
        GROUP BY ds,
                 COALESCE(REFLECT('java.net.URLDecoder', 'decode', PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'id')), PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'id')),
                 CASE COALESCE(REFLECT('java.net.URLDecoder', 'decode', COALESCE(PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'version'), 'Invalid')), COALESCE(PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'version'),'Invalid'))
                     WHEN '%ITEM_VERSION%' THEN 'Invalid'
                     WHEN '' THEN 'Invalid'
                     WHEN NULL THEN 'Invalid'
                     ELSE COALESCE(REFLECT('java.net.URLDecoder', 'decode', COALESCE(PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'version'),'Invalid')), COALESCE(PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'version'),'Invalid'))
                 END,
                 PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'updateType')
        {limit}
    """
