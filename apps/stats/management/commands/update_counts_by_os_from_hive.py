from . import HiveQueryToFileCommand


class Command(HiveQueryToFileCommand):
    """Query the "update counts by os" requests from HIVE, save to disk.

    The data stored locally will then be processed by the
    update_counts_from_file.py script.

    Usage:
    ./manage.py update_counts_by_os_from_hive --date YYYY-MM-DD

    If no date is specified, the default is the day before.
    If not folder is specified, the default is "hive_results". This folder is
    located in <settings.NETAPP_STORAGE>/shared_storage/tmp.

    Example row:

    2014-07-01	0-3z8@uozsdxmbk.co.uk	WINNT	1	112

    """
    help = __doc__
    filename = 'update_counts_by_os.hive'
    query = "select ds , coalesce(reflect('java.net.URLDecoder', 'decode', parse_url(concat('http://www.a.com',request_url), 'QUERY', 'id') ), parse_url(concat('http://www.a.com',request_url), 'QUERY', 'id') ) as id , case coalesce( reflect('java.net.URLDecoder', 'decode', coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appOS'),'Unknown') ), coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appOS'),'Unknown') ) when '%%APP_OS%%' then 'Unknown' when '' then 'Unknown' when null then 'Unknown' else coalesce( reflect('java.net.URLDecoder', 'decode', coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appOS'),'Unknown') ), coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appOS'),'Unknown') ) end as os, count(*), parse_url(concat('http://www.a.com',request_url), 'QUERY', 'updateType') from v2_raw_logs where true and domain = 'versioncheck.addons.mozilla.org' and ds = '%s' and case coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'updateType'),0) when '%%UPDATE_TYPE%%' then 0 when '' then 0 when null then 0 else coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'updateType'),0) end in (0,112) group by ds , coalesce(reflect('java.net.URLDecoder', 'decode', parse_url(concat('http://www.a.com',request_url), 'QUERY', 'id') ), parse_url(concat('http://www.a.com',request_url), 'QUERY', 'id') ) , case coalesce( reflect('java.net.URLDecoder', 'decode', coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appOS'),'Unknown') ), coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appOS'),'Unknown') ) when '%%APP_OS%%' then 'Unknown' when '' then 'Unknown' when null then 'Unknown' else coalesce( reflect('java.net.URLDecoder', 'decode', coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appOS'),'Unknown') ), coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'appOS'),'Unknown') ) end, parse_url(concat('http://www.a.com',request_url), 'QUERY', 'updateType') %s"  # noqa
