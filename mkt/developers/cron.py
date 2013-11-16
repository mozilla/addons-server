import datetime
import logging

import cronjobs
from celery.task.sets import TaskSet

import lib.iarc
from amo.utils import chunked
from lib.iarc.utils import DESC_MAPPING, RATINGS_MAPPING
from mkt.developers.tasks import region_email, region_exclude
from mkt.webapps.models import AddonExcludedRegion, Webapp


log = logging.getLogger('z.mkt.developers.cron')


def _region_email(ids, regions):
    ts = [region_email.subtask(args=[chunk, regions])
          for chunk in chunked(ids, 100)]
    TaskSet(ts).apply_async()


@cronjobs.register
def send_new_region_emails(regions):
    """Email app developers notifying them of new regions added."""
    excluded = (AddonExcludedRegion.objects
                .filter(region__in=[r.id for r in regions])
                .values_list('addon', flat=True))
    ids = (Webapp.objects.exclude(id__in=excluded)
           .filter(enable_new_regions=True)
           .values_list('id', flat=True))
    _region_email(ids, regions)


def _region_exclude(ids, regions):
    ts = [region_exclude.subtask(args=[chunk, regions])
          for chunk in chunked(ids, 100)]
    TaskSet(ts).apply_async()


@cronjobs.register
def exclude_new_region(regions):
    """
    Update regional blacklist based on a list of regions to exclude.
    """
    excluded = (AddonExcludedRegion.objects
                .filter(region__in=[r.id for r in regions])
                .values_list('addon', flat=True))
    ids = (Webapp.objects.exclude(id__in=excluded)
           .filter(enable_new_regions=False)
           .values_list('id', flat=True))
    _region_exclude(ids, regions)


@cronjobs.register
def process_iarc_changes(date=None):
    """
    Queries IARC for recent changes in the past 24 hours (or date provided).

    If date provided use it. It should be in the form YYYY-MM-DD.

    """
    if not date:
        date = datetime.date.today()
    else:
        date = datetime.datetime.strptime(date, '%Y-%m-%d').date()

    client = lib.iarc.client.get_iarc_client('services')
    xml = lib.iarc.utils.render_xml('get_rating_changes.xml', {
        'date_from': date - datetime.timedelta(days=1),
        'date_to': date,
    })
    resp = client.Get_Rating_Changes(XMLString=xml)
    data = lib.iarc.utils.IARC_XML_Parser().parse_string(resp)

    for row in data.get('rows', []):
        iarc_id = row.get('submission_id')
        try:
            app = Webapp.objects.get(iarc_info__submission_id=iarc_id)
        except Webapp.DoesNotExist:
            log.debug('Could not find app associated with IARC submission ID: '
                      '%s' % iarc_id)
            continue

        try:  # Any exceptions we catch, log, and keep going.
            # Process 'new_rating'.
            ratings_body = row.get('rating_system')
            rating = RATINGS_MAPPING[ratings_body].get(row['new_rating'])

            # TODO: If rating is adult, flag for re-review.
            # Save new rating.
            app.set_content_ratings({ratings_body: rating})

            # Process 'new_descriptors'.
            native_descs = filter(None, [
                s.strip() for s in row.get('new_descriptors', '').split(',')])
            descriptors = filter(None, [DESC_MAPPING[ratings_body].get(desc)
                                        for desc in native_descs])
            app.set_descriptors(descriptors)

            # Log change reason.
            reason = row.get('change_reason')
            if reason:
                # TODO: Log to the amo.log tables.
                log.info('New rating for app %s: %s:%s, %s' % (
                    app, ratings_body.name, rating.name, reason))

        except Exception as e:
            log.debug('Exception: %s' % e)
            continue
