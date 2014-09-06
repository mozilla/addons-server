import array
import itertools
import logging
import operator
import os
import subprocess
import time
from datetime import datetime, timedelta

from django.conf import settings
from django.db import connections, transaction
from django.db.models import Q, F, Avg

import cronjobs
import multidb
from lib import recommend
from celery.task.sets import TaskSet
from celeryutils import task
import waffle

import amo
from amo.decorators import write
from amo.utils import chunked, walkfiles
from addons.models import Addon, AppSupport, FrozenAddon, Persona
from files.models import File
from lib.es.utils import raise_if_reindex_in_progress
from stats.models import ThemeUserCount, UpdateCount

log = logging.getLogger('z.cron')
task_log = logging.getLogger('z.task')
recs_log = logging.getLogger('z.recs')


# TODO(jbalogh): removed from cron on 6/27/11. If the site doesn't break,
# delete it.
@cronjobs.register
def fast_current_version():

    # Candidate for deletion - Bug 750510
    if not waffle.switch_is_active('current_version_crons'):
        return
    # Only find the really recent versions; this is called a lot.
    t = datetime.now() - timedelta(minutes=5)
    qs = Addon.objects.values_list('id')
    q1 = qs.filter(status=amo.STATUS_PUBLIC,
                   versions__files__datestatuschanged__gte=t)
    q2 = qs.filter(status__in=amo.UNREVIEWED_STATUSES,
                   versions__files__created__gte=t)
    addons = set(q1) | set(q2)
    if addons:
        _update_addons_current_version(addons)


# TODO(jbalogh): removed from cron on 6/27/11. If the site doesn't break,
# delete it.
@cronjobs.register
def update_addons_current_version():
    """Update the current_version field of the addons."""

    # Candidate for deletion - Bug 750510
    if not waffle.switch_is_active('current_version_crons'):
        return

    d = (Addon.objects.filter(disabled_by_user=False,
                              status__in=amo.VALID_STATUSES)
         .exclude(type=amo.ADDON_PERSONA).values_list('id'))

    ts = [_update_addons_current_version.subtask(args=[chunk])
          for chunk in chunked(d, 100)]
    TaskSet(ts).apply_async()


# TODO(jbalogh): removed from cron on 6/27/11. If the site doesn't break,
# delete it.
@task(rate_limit='20/m')
def _update_addons_current_version(data, **kw):

    # Candidate for deletion - Bug 750510
    if not waffle.switch_is_active('current_version_crons'):
        return

    task_log.info("[%s@%s] Updating addons current_versions." %
                   (len(data), _update_addons_current_version.rate_limit))
    for pk in data:
        try:
            addon = Addon.objects.get(pk=pk[0])
            addon.update_version()
        except Addon.DoesNotExist:
            m = "Failed to update current_version. Missing add-on: %d" % (pk)
            task_log.debug(m)
    transaction.commit_unless_managed()


@cronjobs.register
def update_addon_average_daily_users():
    """Update add-ons ADU totals."""
    raise_if_reindex_in_progress('amo')
    cursor = connections[multidb.get_slave()].cursor()
    q = """SELECT addon_id, AVG(`count`)
           FROM update_counts
           WHERE `date` > DATE_SUB(CURDATE(), INTERVAL 7 DAY)
           GROUP BY addon_id
           ORDER BY addon_id"""
    cursor.execute(q)
    d = cursor.fetchall()
    cursor.close()

    ts = [_update_addon_average_daily_users.subtask(args=[chunk])
          for chunk in chunked(d, 250)]
    TaskSet(ts).apply_async()


@task
def _update_addon_average_daily_users(data, **kw):
    task_log.info("[%s] Updating add-ons ADU totals." % (len(data)))

    for pk, count in data:
        try:
            addon = Addon.objects.get(pk=pk)
        except Addon.DoesNotExist:
            # The processing input comes from metrics which might be out of
            # date in regards to currently existing add-ons
            m = "Got an ADU update (%s) but the add-on doesn't exist (%s)"
            task_log.debug(m % (count, pk))
            continue

        if (count - addon.total_downloads) > 10000:
            # Adjust ADU to equal total downloads so bundled add-ons don't
            # skew the results when sorting by users.
            task_log.info('Readjusted ADU count for addon %s' % addon.slug)
            addon.update(average_daily_users=addon.total_downloads)
        else:
            #task_log.debug('Updating "%s" :: ADU %s -> %s' %
            #               (addon.slug, addon.average_daily_users, count))
            addon.update(average_daily_users=count)


@cronjobs.register
def update_daily_theme_user_counts():
    """Store the day's theme popularity counts into ThemeUserCount."""
    raise_if_reindex_in_progress('amo')
    d = Persona.objects.values_list('addon', 'popularity').order_by('id')

    date = datetime.now().strftime('%M-%d-%y')
    ts = [_update_daily_theme_user_counts.subtask(args=[chunk],
                                                  kwargs={'date': date})
          for chunk in chunked(d, 250)]
    TaskSet(ts).apply_async()


@task
def _update_daily_theme_user_counts(data, **kw):
    task_log.info("[%s] Updating daily theme user counts for %s."
                  % (len(data), kw['date']))

    for pk, count in data:
        ThemeUserCount.objects.create(addon_id=pk, count=count,
                                      date=datetime.now())


@cronjobs.register
def update_addon_download_totals():
    """Update add-on total and average downloads."""
    cursor = connections[multidb.get_slave()].cursor()
    # We need to use SQL for this until
    # http://code.djangoproject.com/ticket/11003 is resolved
    q = """SELECT addon_id, AVG(count), SUM(count)
           FROM download_counts
           USE KEY (`addon_and_count`)
           JOIN addons ON download_counts.addon_id=addons.id
           WHERE addons.status != %s
           GROUP BY addon_id
           ORDER BY addon_id"""
    cursor.execute(q, [amo.STATUS_DELETED])
    d = cursor.fetchall()
    cursor.close()

    ts = [_update_addon_download_totals.subtask(args=[chunk])
          for chunk in chunked(d, 250)]
    TaskSet(ts).apply_async()


@task
def _update_addon_download_totals(data, **kw):
    task_log.info("[%s] Updating add-ons download+average totals." %
                   (len(data)))

    for pk, avg, sum in data:
        try:
            addon = Addon.objects.get(pk=pk)
            # Don't trigger a save unless we have to. Since the query that
            # sends us data doesn't filter out deleted addons, or the addon may
            # be unpopular, this can reduce a lot of unnecessary save queries.
            if (addon.average_daily_downloads != avg or
                addon.total_downloads != sum):
                addon.update(average_daily_downloads=avg, total_downloads=sum)
        except Addon.DoesNotExist:
            # The processing input comes from metrics which might be out of
            # date in regards to currently existing add-ons.
            m = ("Got new download totals (total=%s,avg=%s) but the add-on"
                 "doesn't exist (%s)" % (sum, avg, pk))
            task_log.debug(m)


def _change_last_updated(next):
    # We jump through some hoops here to make sure we only change the add-ons
    # that really need it, and to invalidate properly.
    current = dict(Addon.objects.values_list('id', 'last_updated'))
    changes = {}

    for addon, last_updated in next.items():
        try:
            if current[addon] != last_updated:
                changes[addon] = last_updated
        except KeyError:
            pass

    if not changes:
        return

    log.debug('Updating %s add-ons' % len(changes))
    # Update + invalidate.
    qs = Addon.objects.no_cache().filter(id__in=changes).no_transforms()
    for addon in qs:
        addon.last_updated = changes[addon.id]
        addon.save()


@cronjobs.register
@write
def addon_last_updated():
    next = {}
    for q in Addon._last_updated_queries().values():
        for addon, last_updated in q.values_list('id', 'last_updated'):
            next[addon] = last_updated

    _change_last_updated(next)

    # Get anything that didn't match above.
    other = (Addon.objects.no_cache().filter(last_updated__isnull=True)
             .values_list('id', 'created'))
    _change_last_updated(dict(other))


@cronjobs.register
def update_addon_appsupport():
    # Find all the add-ons that need their app support details updated.
    newish = (Q(last_updated__gte=F('appsupport__created')) |
              Q(appsupport__created__isnull=True))
    # Search providers don't list supported apps.
    has_app = Q(versions__apps__isnull=False) | Q(type=amo.ADDON_SEARCH)
    has_file = Q(versions__files__status__in=amo.VALID_STATUSES)
    good = Q(has_app, has_file) | Q(type=amo.ADDON_PERSONA)
    ids = (Addon.objects.valid().distinct()
           .filter(newish, good).values_list('id', flat=True))

    ts = [_update_appsupport.subtask(args=[chunk])
          for chunk in chunked(ids, 20)]
    TaskSet(ts).apply_async()


@cronjobs.register
def update_all_appsupport():
    from .tasks import update_appsupport
    ids = sorted(set(AppSupport.objects.values_list('addon', flat=True)))
    task_log.info('Updating appsupport for %s addons.' % len(ids))
    for idx, chunk in enumerate(chunked(ids, 100)):
        if idx % 10 == 0:
            task_log.info('[%s/%s] Updating appsupport.'
                          % (idx * 100, len(ids)))
        update_appsupport(chunk)


@task
@transaction.commit_manually
def _update_appsupport(ids, **kw):
    from .tasks import update_appsupport
    update_appsupport(ids)


@cronjobs.register
def addons_add_slugs():
    """Give slugs to any slugless addons."""
    Addon._meta.get_field('modified').auto_now = False
    q = Addon.objects.filter(slug=None).order_by('id')

    # Chunk it so we don't do huge queries.
    for chunk in chunked(q, 300):
        task_log.info('Giving slugs to %s slugless addons' % len(chunk))
        for addon in chunk:
            addon.save()


@cronjobs.register
def hide_disabled_files():
    # If an add-on or a file is disabled, it should be moved to
    # GUARDED_ADDONS_PATH so it's not publicly visible.
    q = (Q(version__addon__status=amo.STATUS_DISABLED)
         | Q(version__addon__disabled_by_user=True))
    ids = (File.objects.filter(q | Q(status=amo.STATUS_DISABLED))
           .values_list('id', flat=True))
    for chunk in chunked(ids, 300):
        qs = File.objects.no_cache().filter(id__in=chunk)
        qs = qs.select_related('version')
        for f in qs:
            f.hide_disabled_file()


@cronjobs.register
def unhide_disabled_files():
    # Files are getting stuck in /guarded-addons for some reason. This job
    # makes sure guarded add-ons are supposed to be disabled.
    log = logging.getLogger('z.files.disabled')
    q = (Q(version__addon__status=amo.STATUS_DISABLED)
         | Q(version__addon__disabled_by_user=True))
    files = set(File.objects.filter(q | Q(status=amo.STATUS_DISABLED))
                .values_list('version__addon', 'filename'))
    for filepath in walkfiles(settings.GUARDED_ADDONS_PATH):
        addon, filename = filepath.split('/')[-2:]
        if tuple([int(addon), filename]) not in files:
            log.warning('File that should not be guarded: %s.' % filepath)
            try:
                file_ = (File.objects.select_related('version__addon')
                         .get(version__addon=addon, filename=filename))
                file_.unhide_disabled_file()
                if (file_.version.addon.status in amo.MIRROR_STATUSES
                    and file_.status in amo.MIRROR_STATUSES):
                    file_.copy_to_mirror()
            except File.DoesNotExist:
                log.warning('File object does not exist for: %s.' % filepath)
            except Exception:
                log.error('Could not unhide file: %s.' % filepath,
                          exc_info=True)


@cronjobs.register
def deliver_hotness():
    """
    Calculate hotness of all add-ons.

    a = avg(users this week)
    b = avg(users three weeks before this week)
    hotness = (a-b) / b if a > 1000 and b > 1 else 0
    """
    frozen = set(f.id for f in FrozenAddon.objects.all())
    all_ids = list((Addon.objects.exclude(type=amo.ADDON_PERSONA)
                   .values_list('id', flat=True)))
    now = datetime.now()
    one_week = now - timedelta(days=7)
    four_weeks = now - timedelta(days=28)
    for ids in chunked(all_ids, 300):
        addons = Addon.objects.no_cache().filter(id__in=ids).no_transforms()
        ids = [a.id for a in addons if a.id not in frozen]
        qs = (UpdateCount.objects.filter(addon__in=ids)
              .values_list('addon').annotate(Avg('count')))
        thisweek = dict(qs.filter(date__gte=one_week))
        threeweek = dict(qs.filter(date__range=(four_weeks, one_week)))
        for addon in addons:
            this, three = thisweek.get(addon.id, 0), threeweek.get(addon.id, 0)
            if this > 1000 and three > 1:
                addon.update(hotness=(this - three) / float(three))
            else:
                addon.update(hotness=0)
        # Let the database catch its breath.
        time.sleep(10)


@cronjobs.register
def recs():
    start = time.time()
    cursor = connections[multidb.get_slave()].cursor()
    cursor.execute("""
        SELECT addon_id, collection_id
        FROM synced_addons_collections ac
        INNER JOIN addons ON
            (ac.addon_id=addons.id AND inactive=0 AND status=4
             AND addontype_id <> 9 AND current_version IS NOT NULL)
        ORDER BY addon_id, collection_id
    """)
    qs = cursor.fetchall()
    recs_log.info('%.2fs (query) : %s rows' % (time.time() - start, len(qs)))
    addons = _group_addons(qs)
    recs_log.info('%.2fs (groupby) : %s addons' %
                  ((time.time() - start), len(addons)))

    if not len(addons):
        return

    # Check our memory usage.
    try:
        p = subprocess.Popen('%s -p%s -o rss' % (settings.PS_BIN, os.getpid()),
                             shell=True, stdout=subprocess.PIPE)
        recs_log.info('%s bytes' % ' '.join(p.communicate()[0].split()))
    except Exception:
        log.error('Could not call ps', exc_info=True)

    sim = recommend.similarity  # Locals are faster.
    sims, start, timers = {}, [time.time()], {'calc': [], 'sql': []}

    def write_recs():
        calc = time.time()
        timers['calc'].append(calc - start[0])
        try:
            _dump_recs(sims)
        except Exception:
            recs_log.error('Error dumping recommendations. SQL issue.',
                           exc_info=True)
        sims.clear()
        timers['sql'].append(time.time() - calc)
        start[0] = time.time()

    for idx, (addon, collections) in enumerate(addons.iteritems(), 1):
        xs = [(other, sim(collections, cs))
              for other, cs in addons.iteritems()]
        # Sort by similarity and keep the top N.
        others = sorted(xs, key=operator.itemgetter(1), reverse=True)
        sims[addon] = [(k, v) for k, v in others[:11] if k != addon]

        if idx % 50 == 0:
            write_recs()
    else:
        write_recs()

    avg_len = sum(len(v) for v in addons.itervalues()) / float(len(addons))
    recs_log.info('%s addons: average length: %.2f' % (len(addons), avg_len))
    recs_log.info('Processing time: %.2fs' % sum(timers['calc']))
    recs_log.info('SQL time: %.2fs' % sum(timers['sql']))


def _dump_recs(sims):
    # Dump a dictionary of {addon: (other_addon, score)} into the
    # addon_recommendations table.
    cursor = connections['default'].cursor()
    addons = sims.keys()
    vals = [(addon, other, score) for addon, others in sims.items()
                                  for other, score in others]
    cursor.execute('BEGIN')
    cursor.execute('DELETE FROM addon_recommendations WHERE addon_id IN %s',
                   [addons])
    cursor.executemany("""
        INSERT INTO addon_recommendations (addon_id, other_addon_id, score)
        VALUES (%s, %s, %s)""", vals)
    cursor.execute('COMMIT')


def _group_addons(qs):
    # qs is a list of (addon_id, collection_id) order by addon_id.
    # Return a dict of {addon_id: [collection_id]}.
    addons = {}
    for addon, collections in itertools.groupby(qs, operator.itemgetter(0)):
        # Skip addons in < 3 collections since we'll be overfitting
        # recommendations to exactly what's in those collections.
        cs = [c[1] for c in collections]
        if len(cs) > 3:
            # array.array() lets us calculate similarities much faster.
            addons[addon] = array.array('l', cs)
    # Don't generate recs for frozen add-ons.
    for addon in FrozenAddon.objects.values_list('addon', flat=True):
        if addon in addons:
            recs_log.info('Skipping frozen addon %s.' % addon)
            del addons[addon]
    return addons


@cronjobs.register
@transaction.commit_on_success
def give_personas_versions():
    cursor = connections['default'].cursor()
    path = os.path.join(settings.ROOT, 'migrations/149-personas-versions.sql')
    with open(path) as f:
        cursor.execute(f.read())
        log.info('Gave versions to %s personas.' % cursor.rowcount)


@cronjobs.register
def reindex_addons(index=None, addon_type=None):
    from . import tasks
    ids = (Addon.objects.values_list('id', flat=True)
           .filter(_current_version__isnull=False,
                   status__in=amo.VALID_STATUSES,
                   disabled_by_user=False))
    if addon_type:
        ids = ids.filter(type=addon_type)
    ts = [tasks.index_addons.subtask(args=[chunk], kwargs=dict(index=index))
          for chunk in chunked(sorted(list(ids)), 150)]
    TaskSet(ts).apply_async()
