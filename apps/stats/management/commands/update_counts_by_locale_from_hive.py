from . import HiveQueryToFileCommand


class Command(HiveQueryToFileCommand):
    """Query the "update counts by locale" requests from HIVE, save to disk.

    The data stored locally will then be processed by the
    update_counts_from_file.py script.

    Usage:
    ./manage.py update_counts_by_locale_from_hive --date YYYY-MM-DD

    If no date is specified, the default is the day before.
    If not folder is specified, the default is "hive_results". This folder is
    located in <settings.NETAPP_STORAGE>/tmp.

    Example row:

    2014-07-01	0-107@hhyayt.com	en-US	1	112

    """
    help = __doc__
    filename = 'update_counts_by_locale.hive'
    query = """
        SELECT ds ,
               coalesce(reflect('java.net.URLDecoder', 'decode', parse_url(concat('http://www.a.com', request_url), 'QUERY', 'id')), parse_url(concat('http://www.a.com',request_url), 'QUERY', 'id')) AS id ,
               CASE coalesce(reflect('java.net.URLDecoder', 'decode', coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'locale'),'Unknown')), coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'locale'),'Unknown'))
                   WHEN '%APP_LOCALE%' THEN 'Unknown'
                   WHEN '' THEN 'Unknown'
                   WHEN NULL THEN 'Unknown'
                   ELSE coalesce(reflect('java.net.URLDecoder', 'decode', coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'locale'),'Unknown')), coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'locale'),'Unknown'))
               END AS locale ,
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
                 CASE coalesce(reflect('java.net.URLDecoder', 'decode', coalesce(parse_url(concat('http://www.a.com', request_url), 'QUERY', 'locale'),'Unknown')), coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'locale'),'Unknown'))
                     WHEN '%APP_LOCALE%' THEN 'Unknown'
                     WHEN '' THEN 'Unknown'
                     WHEN NULL THEN 'Unknown'
                     ELSE coalesce(reflect('java.net.URLDecoder', 'decode', coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'locale'),'Unknown')), coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'locale'),'Unknown'))
                 END,
                 parse_url(concat('http://www.a.com',request_url), 'QUERY', 'updateType')
        {limit}
    """
