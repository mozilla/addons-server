import base64
import collections
import hashlib
from datetime import datetime
from operator import attrgetter
import time

from django.core.cache import cache
from django.db.models import Q, signals as db_signals
from django.shortcuts import get_object_or_404
from django.utils.cache import patch_cache_control
from django.utils.encoding import smart_str

import jingo

from amo.utils import sorted_groupby
from amo.tasks import flush_front_end_cache_urls
from versions.compare import version_int
from .models import (BlocklistApp, BlocklistCA, BlocklistDetail, BlocklistGfx,
                     BlocklistItem, BlocklistPlugin)


App = collections.namedtuple('App', 'guid min max')
BlItem = collections.namedtuple('BlItem', 'rows os modified block_id')


def blocklist(request, apiver, app, appver):
    key = 'blocklist:%s:%s:%s' % (apiver, app, appver)
    # Use md5 to make sure the memcached key is clean.
    key = hashlib.md5(smart_str(key)).hexdigest()
    cache.add("blocklist:keyversion", 1)
    version = cache.get("blocklist:keyversion")
    response = cache.get(key, version=version)
    if response is None:
        response = _blocklist(request, apiver, app, appver)
        cache.set(key, response, 60 * 60, version=version)
    patch_cache_control(response, max_age=60 * 60)
    return response


def _blocklist(request, apiver, app, appver):
    apiver = int(apiver)
    items = get_items(apiver, app, appver)[0]
    plugins = get_plugins(apiver, app, appver)
    gfxs = BlocklistGfx.objects.filter(Q(guid__isnull=True) | Q(guid=app))
    cas = None

    try:
        cas = BlocklistCA.objects.all()[0]
        cas = base64.b64encode(cas.data)
    except IndexError:
        pass

    # Find the latest created/modified date across all sections.
    all_ = list(items.values()) + list(plugins) + list(gfxs)
    last_update = max(x.modified for x in all_) if all_ else datetime.now()
    # The client expects milliseconds, Python's time returns seconds.
    last_update = int(time.mktime(last_update.timetuple()) * 1000)
    data = dict(items=items, plugins=plugins, gfxs=gfxs, apiver=apiver,
                appguid=app, appver=appver, last_update=last_update, cas=cas)
    return jingo.render(request, 'blocklist/blocklist.xml', data,
                        content_type='text/xml')


def clear_blocklist(*args, **kw):
    # Something in the blocklist changed; invalidate all responses.
    cache.add("blocklist:keyversion", 1)
    cache.incr("blocklist:keyversion")
    flush_front_end_cache_urls.delay(['/blocklist/*'])


for m in (BlocklistItem, BlocklistPlugin, BlocklistGfx, BlocklistApp,
          BlocklistCA, BlocklistDetail):
    db_signals.post_save.connect(clear_blocklist, sender=m,
                                 dispatch_uid='save_%s' % m)
    db_signals.post_delete.connect(clear_blocklist, sender=m,
                                   dispatch_uid='delete_%s' % m)


def get_items(apiver, app, appver=None):
    # Collapse multiple blocklist items (different version ranges) into one
    # item and collapse each item's apps.
    addons = (BlocklistItem.uncached
              .select_related('details')
              .filter(Q(app__guid__isnull=True) | Q(app__guid=app))
              .order_by('-modified')
              .extra(select={'app_guid': 'blapps.guid',
                             'app_min': 'blapps.min',
                             'app_max': 'blapps.max'}))
    items, details = {}, {}
    for guid, rows in sorted_groupby(addons, 'guid'):
        rows = list(rows)
        rr = []
        for id, rs in sorted_groupby(rows, 'id'):
            rs = list(rs)
            rr.append(rs[0])
            rs[0].apps = [App(r.app_guid, r.app_min, r.app_max)
                           for r in rs if r.app_guid]
        os = [r.os for r in rr if r.os]
        items[guid] = BlItem(rr, os[0] if os else None, rows[0].modified,
                             rows[0].block_id)
        details[guid] = sorted(rows, key=attrgetter('id'))[0]
    return items, details


def get_plugins(apiver, app, appver=None):
    # API versions < 3 ignore targetApplication entries for plugins so only
    # block the plugin if the appver is within the block range.
    plugins = (BlocklistPlugin.uncached.select_related('details')
               .filter(Q(guid__isnull=True) | Q(guid=app)))
    if apiver < 3 and appver is not None:
        def between(ver, min, max):
            if not (min and max):
                return True
            return version_int(min) < ver < version_int(max)
        app_version = version_int(appver)
        plugins = [p for p in plugins if between(app_version, p.min, p.max)]
    return list(plugins)


def blocked_list(request, apiver=3):
    app = request.APP.guid
    objs = get_items(apiver, app)[1].values() + get_plugins(apiver, app)
    items = sorted(objs, key=attrgetter('created'), reverse=True)
    return jingo.render(request, 'blocklist/blocked_list.html',
                        {'items': items})


# The id is prefixed with [ip] so we know which model to use.
def blocked_detail(request, id):
    bltypes = dict((m._type, m) for m in (BlocklistItem, BlocklistPlugin))
    item = get_object_or_404(bltypes[id[0]], details=id[1:])
    return jingo.render(request, 'blocklist/blocked_detail.html',
                        {'item': item})
