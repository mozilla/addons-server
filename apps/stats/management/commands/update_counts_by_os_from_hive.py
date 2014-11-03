# flake8: noqa
from . import HiveQueryToFileCommand


class Command(HiveQueryToFileCommand):
    """Query the "update counts by os" requests from HIVE, save to disk.

    The data stored locally will then be processed by the
    update_counts_from_file.py script.

    Usage:
    ./manage.py update_counts_by_os_from_hive --date YYYY-MM-DD

    If no date is specified, the default is the day before.
    If not folder is specified, the default is "hive_results". This folder is
    located in <settings.NETAPP_STORAGE>/tmp.

    Example row:

    2014-07-01	0-3z8@uozsdxmbk.co.uk	WINNT	1	112

    """
    help = __doc__
    filename = 'update_counts_by_os.hive'
    query = """
        SELECT DS ,
               COALESCE(REFLECT('java.net.URLDecoder', 'decode', PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'id')), PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'id')) AS ID ,
               CASE COALESCE(REFLECT('java.net.URLDecoder', 'decode', COALESCE(PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'appOS'),'Unknown')), COALESCE(PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'appOS'),'Unknown'))
                   WHEN '%APP_OS%' THEN 'Unknown'
                   WHEN '' THEN 'Unknown'
                   WHEN NULL THEN 'Unknown'
                   ELSE COALESCE(REFLECT('java.net.URLDecoder', 'decode', COALESCE(PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'appOS'),'Unknown')), COALESCE(PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'appOS'), 'Unknown'))
               END AS OS ,
               COUNT(*),
               PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'updateType')
        FROM V2_RAW_LOGS
        WHERE
            TRUE AND
            DOMAIN = 'versioncheck.addons.mozilla.org' AND
            DS = '{day}' AND
            {ip_filtering}
        GROUP BY DS ,
                 COALESCE(REFLECT('java.net.URLDecoder', 'decode', PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'id')), PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'id')) ,
                 CASE COALESCE(REFLECT('java.net.URLDecoder', 'decode', COALESCE(PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'appOS'), 'Unknown')), COALESCE(PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'appOS'),'Unknown'))
                     WHEN '%APP_OS%' THEN 'Unknown'
                     WHEN '' THEN 'Unknown'
                     WHEN NULL THEN 'Unknown'
                     ELSE COALESCE(REFLECT('java.net.URLDecoder', 'decode', COALESCE(PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'appOS'),'Unknown')), COALESCE(PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'appOS'), 'Unknown'))
                 END,
                 PARSE_URL(CONCAT('http://www.a.com',request_url), 'QUERY', 'updateType')
        {limit}
    """
