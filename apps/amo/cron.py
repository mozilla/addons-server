import calendar
import json
import re
import time
import urllib2
from datetime import datetime, timedelta
from subprocess import Popen, PIPE

from django.conf import settings

from celeryutils import task
import cronjobs
import commonware.log
import phpserialize
import redisutils

import amo
from amo.utils import chunked
from addons.models import Addon, AddonCategory
from addons.utils import AdminActivityLogMigrationTracker, MigrationTracker
from applications.models import Application, AppVersion
from bandwagon.models import Collection, CollectionAddon
from cake.models import Session
from devhub.models import ActivityLog, LegacyAddonLog
from editors.models import EventLog
from files.models import Approval, File, TestResultCache
from reviews.models import Review
from sharing import SERVICES_LIST
from tags.models import AddonTag
from stats.models import AddonShareCount, Contribution
from users.models import UserProfile

log = commonware.log.getLogger('z.cron')


@cronjobs.register
def gc(test_result=True):
    "Site-wide garbage collections."

    three_months_ago = datetime.today() - timedelta(days=90)
    six_days_ago = datetime.today() - timedelta(days=6)
    two_days_ago = datetime.today() - timedelta(days=2)
    one_hour_ago = datetime.today() - timedelta(hours=1)

    log.debug('Cleaning up sessions table.')
    # cake.Session is stupid so...
    two_days_ago_unixtime = calendar.timegm(two_days_ago.utctimetuple())
    Session.objects.filter(expires__lt=two_days_ago_unixtime).delete()

    log.debug('Cleaning up sharing services.')
    AddonShareCount.objects.exclude(
            service__in=[s.shortname for s in SERVICES_LIST]).delete()

    log.debug('Cleaning up test results cache.')
    TestResultCache.objects.filter(date__lt=one_hour_ago).delete()

    log.debug('Cleaning up test results extraction cache.')
    if settings.NETAPP_STORAGE and settings.NETAPP_STORAGE != '/':
        cmd = ('find', settings.NETAPP_STORAGE, '-maxdepth', '1', '-name',
               'validate-*', '-mtime', '+7', '-type', 'd',
               '-exec', 'rm', '-rf', "{}", ';')

        output = Popen(cmd, stdout=PIPE).communicate()[0]

        for line in output.split("\n"):
            log.debug(line)

    else:
        log.warning('NETAPP_STORAGE not defined.')

    if settings.COLLECTIONS_ICON_PATH:
        log.debug('Cleaning up uncompressed icons.')

        cmd = ('find', settings.COLLECTIONS_ICON_PATH,
               '-name', '*__unconverted', '-mtime', '+1', '-type', 'f',
               '-exec', 'rm', '{}', ';')
        output = Popen(cmd, stdout=PIPE).communicate()[0]

        for line in output.split("\n"):
            log.debug(line)

    if settings.USERPICS_PATH:
        log.debug('Cleaning up uncompressed userpics.')

        cmd = ('find', settings.USERPICS_PATH,
               '-name', '*__unconverted', '-mtime', '+1', '-type', 'f',
               '-exec', 'rm', '{}', ';')
        output = Popen(cmd, stdout=PIPE).communicate()[0]

        for line in output.split("\n"):
            log.debug(line)

    # Paypal only keeps retrying to verify transactions for up to 3 days. If we
    # still have an unverified transaction after 6 days, we might as well get
    # rid of it.
    log.debug('Cleaning up outdated contributions statistics.')
    Contribution.objects.filter(transaction_id__isnull=True,
                                created__lt=six_days_ago).delete()

    log.debug('Removing old entries from add-on news feeds.')

    ActivityLog.objects.filter(created__lt=three_months_ago).exclude(
            action__in=amo.LOG_KEEP).delete()

    log.debug('Cleaning up anonymous collections.')
    Collection.objects.filter(created__lt=two_days_ago,
                              type=amo.COLLECTION_ANONYMOUS).delete()


@cronjobs.register
def migrate_admin_logs():
    # Get the highest id we've looked at.
    a = AdminActivityLogMigrationTracker()
    id = a.get() or 0

    # filter here for addappversion
    items = LegacyAddonLog.objects.filter(
            type=amo.LOG.ADD_APPVERSION.id, pk__gt=id).values_list(
            'id', flat=True)
    for chunk in chunked(items, 100):
        _migrate_admin_logs.delay(chunk)
        a.set(chunk[-1])


@task
def _migrate_admin_logs(items, **kw):
    print 'Processing: %d..%d' % (items[0], items[-1])
    for item in LegacyAddonLog.objects.filter(pk__in=items):
        kw = dict(user=item.user, created=item.created)
        amo.log(amo.LOG.ADD_APPVERSION, (Application, item.object1_id),
                (AppVersion, item.object2_id), **kw)


# TODO(davedash): remove after /editors is on zamboni
@cronjobs.register
def migrate_editor_eventlog():
    a = MigrationTracker('eventlog')
    id = a.get() or 0

    items = EventLog.objects.filter(type='editor', pk__gt=id).values_list(
            'id', flat=True)

    for chunk in chunked(items, 100):
        _migrate_editor_eventlog(chunk)
        a.set(chunk[-1])


@task
def _migrate_editor_eventlog(items, **kw):
    log.info('[%s@%s] Migrating eventlog items' %
             (len(items), _migrate_editor_eventlog.rate_limit))
    for item in EventLog.objects.filter(pk__in=items):
        kw = dict(user=item.user, created=item.created)
        if item.action == 'review_delete':
            details = None
            try:
                details = phpserialize.loads(item.notes)
            except ValueError:
                pass
            amo.log(amo.LOG.DELETE_REVIEW, item.changed_id, details=details,
                    **kw)
        elif item.action == 'review_approve':
            try:
                r = Review.objects.get(pk=item.changed_id)
                amo.log(amo.LOG.ADD_REVIEW, r, r.addon, **kw)
            except Review.DoesNotExist:
                log.warning("Couldn't find review for %d" % item.changed_id)


# TODO(davedash): remove aftr /editors is on zamboni
@cronjobs.register
def migrate_approvals():
    a = MigrationTracker('approvals')
    id = a.get() or 0

    items = (Approval.objects.filter(pk__gt=id).order_by('id')
                             .values_list('id', flat=True))

    for chunk in chunked(items, 100):
        _migrate_approvals(chunk)
        a.set(chunk[-1])


@task
def _migrate_approvals(items, **kw):
    log.info('[%s@%s] Migrating approval items' %
             (len(items), _migrate_approvals.rate_limit))
    for item in Approval.objects.filter(pk__in=items):
        try:
            args = (item.addon, item.file.version)
        except File.DoesNotExist:
            log.warning("Couldn't find file for approval %d" % item.id)
            continue

        kw = dict(user=item.user, created=item.created,
                  details=dict(comments=item.comments,
                               reviewtype=item.reviewtype))
        if item.action == amo.STATUS_PUBLIC:
            amo.log(amo.LOG.APPROVE_VERSION, *args, **kw)
        elif item.action == amo.STATUS_LITE:
            amo.log(amo.LOG.PRELIMINARY_VERSION, *args, **kw)
        elif item.action == amo.STATUS_NULL:
            amo.log(amo.LOG.REJECT_VERSION, *args, **kw)
        elif item.action in (amo.STATUS_PENDING, amo.STATUS_NOMINATED):
            amo.log(amo.LOG.ESCALATE_VERSION, *args, **kw)
        elif item.action == amo.STATUS_UNREVIEWED:
            amo.log(amo.LOG.RETAIN_VERSION, *args, **kw)
        else:
            log.warning('Unknown action: %d' % item.action)


@cronjobs.register
def dissolve_outgoing_urls():
    """Over time, some outgoing.m.o URLs have been encoded several times in the
    db.  This removes the layers of encoding and sets URLs to their real value.
    The app will take care of sending things through outgoing.m.o.  See bug
    608117."""

    needle = 'outgoing.mozilla.org'

    users = (UserProfile.objects.filter(homepage__contains=needle)
             .values_list('id', 'homepage'))

    if not users:
        print "Didn't find any add-ons with messed up homepages."
        return

    print 'Found %s users to fix.  Sending them to celeryd.' % len(users)

    for chunk in chunked(users, 100):
        _dissolve_outgoing_urls.delay(chunk)


@task(rate_limit='60/h')
def _dissolve_outgoing_urls(items, **kw):
    log.info('[%s@%s] Dissolving outgoing urls' %
             (len(items), _dissolve_outgoing_urls.rate_limit))

    regex = re.compile('^http://outgoing.mozilla.org/v1/[0-9a-f]+/(.*?)$')

    def peel_the_onion(url):
        match = regex.match(url)

        if not match:
            return None

        new = urllib2.unquote(match.group(1))
        are_we_there_yet = peel_the_onion(new)  # That's right. You love it.

        if not are_we_there_yet:
            return new
        else:
            return are_we_there_yet

    for user in items:
        url = peel_the_onion(user[1])

        # 20 or so of these are just to outgoing.m.o, so just whack them
        if url == 'http://outgoing.mozilla.org':
            url = None

        UserProfile.objects.filter(pk=user[0]).update(homepage=url)


# TODO(davedash): Remove after 5.12.7 is pushed.
@cronjobs.register
def activity_log_scrubber():
    """
    Scans activity log for REMOVE_FROM_COLLECTION and ADD_TO_COLLECTION, looks
    for collections in arguments and checks whether collection is listed.
    """

    items = (ActivityLog.objects.filter(
             action__in=[amo.LOG.ADD_TO_COLLECTION.id,
                         amo.LOG.REMOVE_FROM_COLLECTION.id])
             .values('id', '_arguments'))
    ids = []
    count = 0
    # ~127K
    for item in items:
        count += 1
        for k in json.loads(item['_arguments']):
            if 'bandwagon.collection' not in k:
                continue
            if not all(Collection.objects.filter(pk=k.values()[0])
                       .values_list('listed', flat=True)):
                log.debug('%d items seen.' % count)
                ids.append(item['id'])
        if len(ids) > 100:
            _activity_log_scrubber.delay(ids)
            ids = []

    # get everyone else
    _activity_log_scrubber.delay(ids)


@task(rate_limit='60/h')
def _activity_log_scrubber(items, **kw):
    log.info('[%s@%s] Deleting activity log items' %
             (len(items), _activity_log_scrubber.rate_limit))

    ActivityLog.objects.filter(id__in=items).delete()


class QueueCheck(object):
    key = 'cron:queuecheck:%s:%s'

    def __init__(self):
        self.redis = redisutils.connections['master']

    def queues(self):
        # Figure out all the queues we're using. celery is the default, with a
        # warning threshold of 10 minutes.
        queues = {'celery': 60 * 60}
        others = set(r['queue'] for r in settings.CELERY_ROUTES.values())
        # 30 second threshold for the fast queues.
        queues.update((q, 30) for q in others)
        return queues

    def set(self, action, queue):
        self.redis.set(self.key % (action, queue), time.time())

    def get(self, action, queue):
        return self.redis.get(self.key % (action, queue))


@cronjobs.register
def check_queues():
    checker = QueueCheck()
    for queue in checker.queues():
        checker.set('ping', queue)
        ping.apply_async(queue=queue, routing_key=queue, exchange=queue)


@task
def ping(**kw):
    queue = kw['delivery_info']['routing_key']
    log.info('[1@None] Checking the %s queue' % queue)
    QueueCheck().set('pong', queue)


# TODO(davedash): run once
@cronjobs.register
def delete_brand_thunder_addons():
    ids = (102188, 102877, 103381, 103382, 103388, 107864, 109233, 109242,
           111144, 111145, 115970, 150367, 146373, 143547, 142886, 140931,
           113511, 100304, 130876, 126516, 124495, 123900, 120683, 159626,
           159625, 157780, 157776, 155494, 155489, 155488, 152740, 152739,
           151187, 193275, 184048, 182866, 179429, 179426, 161783, 161781,
           161727, 160426, 160425, 220155, 219726, 219724, 219723, 219722,
           218413, 200756, 200755, 199904, 221522, 221521, 221520, 221513,
           221509, 221508, 221505, 220882, 220880, 220879, 223384, 223383,
           223382, 223381, 223380, 223379, 223378, 223376, 222194, 221524,
           223403, 223402, 223400, 223399, 223398, 223388, 223387, 223386,
           223385, 232687, 232681, 228394, 228393, 228392, 228391, 228390,
           226428, 226427, 226388, 235892, 235836, 235277, 235276, 235274,
           232709, 232708, 232707, 232694, 232688, 94461, 94452, 54288, 50418,
           49362, 49177, 239113, 102186, 102185, 101166, 101165, 101164,
           99010, 99007, 99006, 98429, 98428, 45834, 179542, 103383)

    for addon in (UserProfile.objects.get(email='patrick@brandthunder.com')
                  .addons.filter(pk__in=ids)):
        try:
            addon.delete('Deleting per Brand Thunder request (bug 636834).')
        except:
            log.error('Could not delete add-on %d' % addon.id)
