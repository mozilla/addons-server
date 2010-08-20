import calendar
from datetime import datetime, timedelta
from subprocess import Popen, PIPE

from django.conf import settings

import cronjobs
import commonware.log

import amo
from bandwagon.models import Collection
from cake.models import Session
from devhub.models import AddonLog, LOG as ADDONLOG
from files.models import TestResult, TestResultCache
from sharing.models import SERVICES
from stats.models import ShareCount, Contribution

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
    ShareCount.objects.exclude(
            service__in=[s.shortname for s in SERVICES]).delete()

    # XXX(davedash): I can't seem to run this during testing without triggering
    # an error: "test_remora.nose_c doesn't exist"
    # for some reason a ForeignKey attaches itself to TestResult during testing
    # I suspect it's the name, but I don't have time to really figure this out.
    if test_result:
        log.debug('Cleaning up test results.')
        TestResult.objects.filter(created__lt=one_hour_ago).delete()

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
    keep = (
            ADDONLOG['Create Add-on'],
            ADDONLOG['Add User with Role'],
            ADDONLOG['Remove User with Role'],
            ADDONLOG['Set Inactive'],
            ADDONLOG['Unset Inactive'],
            ADDONLOG['Change Status'],
            ADDONLOG['Add Version'],
            ADDONLOG['Delete Version'],
            ADDONLOG['Approve Version'],
            ADDONLOG['Retain Version'],
            ADDONLOG['Escalate Version'],
            ADDONLOG['Request Version'],
            ADDONLOG['Add Recommended'],
            ADDONLOG['Remove Recommended'],
            )
    AddonLog.objects.filter(created__lt=three_months_ago).exclude(
            type__in=keep).delete()

    log.debug('Cleaning up anonymous collections.')
    Collection.objects.filter(created__lt=two_days_ago,
                              type=amo.COLLECTION_ANONYMOUS).delete()
