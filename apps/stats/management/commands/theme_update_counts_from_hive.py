from . import HiveQueryToFileCommand


class Command(HiveQueryToFileCommand):
    """Query the "theme update counts" requests from HIVE, save to disk.

    The data stored locally will then be processed by the
    theme_update_counts_from_file.py script.

    Usage:
    ./manage.py theme_update_counts_from_hive --date YYYY-MM-DD

    If no date is specified, the default is the day before.
    If not folder is specified, the default is "hive_results". This folder is
    located in <settings.NETAPP_STORAGE>/tmp.

    Example row:

    2014-07-01	123	gp	112

    """
    help = __doc__
    filename = 'theme_update_counts.hive'
    query = r"""
        select
             ds
           -- this "id" can be a persona_id (when src=gp) or an addon_id (src is null)
           , regexp_extract(request_url, '^/([-\\w]+)(/themes/update-check/)(\\d+).*', 3) as id
           , parse_url(concat('http://www.a.com',request_url), 'QUERY', 'src') as src
           , count(1) as requests
        from v2_raw_logs
        where true
          and domain = "versioncheck.addons.mozilla.org"
          and ds = '%s'
          -- fast filters:
          and request_url like '%%update-check%%'
          -- takes more time but it's the correct filter:
          and regexp_extract(request_url, '^/([-\\w]+)(/themes/update-check/)(\\d+).*', 2) = '/themes/update-check/'
          group by
             ds
           , regexp_extract(request_url, '^/([-\\w]+)(/themes/update-check/)(\\d+).*', 3)
           , parse_url(concat('http://www.a.com',request_url), 'QUERY', 'src')
        -- limit
        %s
    """  # noqa
