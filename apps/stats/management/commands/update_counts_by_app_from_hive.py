from . import HiveQueryToFileCommand


class Command(HiveQueryToFileCommand):
    """Query the "update counts by app" requests from HIVE, save to disk.

    The data stored locally will then be processed by the
    update_counts_from_file.py script.

    Usage:
    ./manage.py update_counts_by_app_from_hive --date YYYY-MM-DD

    If no date is specified, the default is the day before.
    If not folder is specified, the default is "hive_results". This folder is
    located in <settings.NETAPP_STORAGE>/tmp.

    Example row:

    2014-07-01	a@j.co.uk	{ec8030f7-c20a-464f-9b0e-13a3a9e97384}	30.0	1	112

    """
    help = __doc__
    filename = 'update_counts_by_app.hive'
    query = """
        SELECT ds ,
               coalesce(reflect('java.net.URLDecoder', 'decode', parse_url(concat('http://www.a.com', request_url), 'QUERY', 'id')), parse_url(concat('http://www.a.com',request_url), 'QUERY', 'id')) AS id ,
               CASE coalesce(reflect('java.net.URLDecoder', 'decode', coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appID'),'Invalid')), coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appID'),'Invalid'))
                   WHEN '%APP_ID%' THEN 'Invalid'
                   WHEN '' THEN 'Invalid'
                   WHEN NULL THEN 'Invalid'
                   ELSE coalesce(reflect('java.net.URLDecoder', 'decode', coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appID'),'Invalid')), coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appID'),'Invalid'))
               END AS product_guid ,
               CASE coalesce(reflect('java.net.URLDecoder', 'decode', coalesce(parse_url(concat('http://www.a.com', request_url), 'QUERY', 'appVersion'),'Invalid')), coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appVersion'),'Invalid'))
                   WHEN '%APP_VERSION%' THEN 'Invalid'
                   WHEN '' THEN 'Invalid'
                   WHEN NULL THEN 'Invalid'
                   ELSE coalesce(reflect('java.net.URLDecoder', 'decode', coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appVersion'),'Invalid')), coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appVersion'),'Invalid'))
               END AS product_version ,
               count(*),
               parse_url(concat('http://www.a.com',request_url), 'QUERY', 'updateType')
        FROM v2_raw_logs
        WHERE
          TRUE AND
          DOMAIN = 'versioncheck.addons.mozilla.org' AND
          ds = '{day}' AND
          {ip_filtering}
        GROUP BY ds ,
                 coalesce(reflect('java.net.URLDecoder', 'decode', parse_url(concat('http://www.a.com',request_url), 'QUERY', 'id')), parse_url(concat('http://www.a.com',request_url), 'QUERY', 'id')) ,
                 CASE coalesce(reflect('java.net.URLDecoder', 'decode', coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appID'),'Invalid')), coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appID'),'Invalid'))
                     WHEN '%APP_ID%' THEN 'Invalid'
                     WHEN '' THEN 'Invalid'
                     WHEN NULL THEN 'Invalid'
                     ELSE coalesce(reflect('java.net.URLDecoder', 'decode', coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appID'),'Invalid')), coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appID'),'Invalid'))
                 END ,
                 CASE coalesce(reflect('java.net.URLDecoder', 'decode', coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appVersion'),'Invalid')), coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appVersion'),'Invalid'))
                     WHEN '%APP_VERSION%' THEN 'Invalid'
                     WHEN '' THEN 'Invalid'
                     WHEN NULL THEN 'Invalid'
                     ELSE coalesce(reflect('java.net.URLDecoder', 'decode', coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appVersion'),'Invalid')), coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appVersion'),'Invalid'))
                 END,
                 parse_url(concat('http://www.a.com',request_url), 'QUERY', 'updateType')
        {limit}
    """
