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
    query = "select ds, coalesce(reflect('java.net.URLDecoder', 'decode', parse_url(concat('http://www.a.com',request_url), 'QUERY', 'id') ), parse_url(concat('http://www.a.com',request_url), 'QUERY', 'id')) as id, case coalesce( reflect('java.net.URLDecoder', 'decode', coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'version'),'Invalid') ), coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'version'),'Invalid')) when '%%ITEM_VERSION%%' then 'Invalid' when '' then 'Invalid' when null then 'Invalid' else coalesce( reflect('java.net.URLDecoder', 'decode', coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'version'),'Invalid') ), coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'version'),'Invalid')) end as version, count(*), parse_url(concat('http://www.a.com',request_url), 'QUERY', 'updateType') from v2_raw_logs where true and domain = 'versioncheck.addons.mozilla.org' and ds = '%s' group by ds, coalesce(reflect('java.net.URLDecoder', 'decode', parse_url(concat('http://www.a.com',request_url), 'QUERY', 'id') ), parse_url(concat('http://www.a.com',request_url), 'QUERY', 'id')), case coalesce( reflect('java.net.URLDecoder', 'decode', coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'version'),'Invalid') ), coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'version'),'Invalid')) when '%%ITEM_VERSION%%' then 'Invalid' when '' then 'Invalid' when null then 'Invalid' else coalesce( reflect('java.net.URLDecoder', 'decode', coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'version'),'Invalid') ), coalesce(parse_url(concat('http://www.a.com',request_url), 'QUERY', 'version'),'Invalid')) end, parse_url(concat('http://www.a.com',request_url), 'QUERY', 'updateType') %s"  # noqa
