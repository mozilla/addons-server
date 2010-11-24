import calendar
from datetime import datetime, timedelta
from subprocess import Popen, PIPE

from django.conf import settings

from celeryutils import task
import cronjobs
import commonware.log

import amo
from amo.utils import chunked
from addons.utils import ActivityLogMigrationTracker
from bandwagon.models import Collection
from cake.models import Session
from devhub.models import ActivityLog, LegacyAddonLog
from files.models import TestResultCache
from sharing import SERVICES_LIST
from stats.models import AddonShareCount, Contribution
from users.models import UserProfile
from versions.models import Version

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
def migrate_logs():
    # Get the highest id we've looked at.
    a = ActivityLogMigrationTracker()
    id = a.get() or 0

    items = LegacyAddonLog.objects.filter(pk__gt=id).values_list(
            'id', flat=True)
    for chunk in chunked(items, 100):
        _migrate_logs.delay(chunk)
        a.set(chunk[-1])


@task
def _migrate_logs(items, **kw):
    print 'Processing: %d..%d' % (items[0], items[-1])
    for item in LegacyAddonLog.objects.filter(pk__in=items):
        kw = dict(user=item.user, created=item.created)
        if item.type not in amo.LOG_KEEP:
            continue
        elif item.type in [amo.LOG.CREATE_ADDON.id, amo.LOG.SET_INACTIVE.id,
                           amo.LOG.UNSET_INACTIVE.id,
                           amo.LOG.SET_PUBLIC_STATS.id,
                           amo.LOG.UNSET_PUBLIC_STATS.id,
                           amo.LOG.ADD_RECOMMENDED.id,
                           amo.LOG.REMOVE_RECOMMENDED.id]:
            amo.log(amo.LOG_BY_ID[item.type], item.addon, **kw)

        elif item.type in [amo.LOG.ADD_USER_WITH_ROLE.id,
                           amo.LOG.REMOVE_USER_WITH_ROLE.id]:
            amo.log(amo.LOG_BY_ID[item.type], item.addon,
                    (UserProfile, item.object1_id),
                    unicode(dict(amo.AUTHOR_CHOICES)[item.object2_id]), **kw)
        elif item.type == amo.LOG.CHANGE_STATUS.id:
            amo.log(amo.LOG_BY_ID[item.type], item.addon,
                    unicode(amo.STATUS_CHOICES[item.object1_id]), **kw)
        # Items that require only a version
        elif item.type in [amo.LOG.ADD_VERSION.id,
                           amo.LOG.APPROVE_VERSION.id,
                           amo.LOG.RETAIN_VERSION.id,
                           amo.LOG.ESCALATE_VERSION.id,
                           amo.LOG.REQUEST_VERSION.id]:
            try:
                v = Version.objects.get(pk=item.object1_id)
                amo.log(amo.LOG_BY_ID[item.type], item.addon, v, **kw)
            except Version.DoesNotExist:
                print ('Version %d does not exist.  No worries, it happens.'
                       % item.object1_id)
        elif item.type == amo.LOG.DELETE_VERSION.id:
            amo.log(amo.LOG_BY_ID[item.type], item.addon, item.name1, **kw)
