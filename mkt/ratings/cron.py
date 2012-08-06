import datetime

from django.conf import settings

import commonware.log
import cronjobs
import waffle

import amo
from amo.utils import send_mail_jinja
from reviews.models import Review

cron_log = commonware.log.getLogger('mkt.ratings.cron')


@cronjobs.register
def email_daily_ratings():
    """
    Does email for yesterday's ratings (right after the day has passed).
    Sends an email containing all reviews for that day for certain app.
    """
    if not waffle.switch_is_active('ratings'):
        return

    dt = datetime.datetime.today() - datetime.timedelta(1)
    yesterday = datetime.datetime(dt.year, dt.month, dt.day, 0, 0, 0)
    today = yesterday + datetime.timedelta(1)
    pretty_date = '%04d-%02d-%02d' % (dt.year, dt.month, dt.day)

    yesterday_reviews = Review.objects.filter(created__gte=yesterday,
                                              created__lt=today,
                                              addon__type=amo.ADDON_WEBAPP)

    # For each app in yesterday's set of reviews, gather reviews and email out.
    apps = set(review.addon for review in yesterday_reviews)
    for app in apps:
        # Email all reviews in one email for current app in loop.
        author_emails = app.authors.values_list('email', flat=True)
        subject = 'Firefox Marketplace reviews for %s on %s' % (app.name,
                                                                pretty_date)

        context = {'reviews': (yesterday_reviews.filter(addon=app).
                               order_by('-created')),
                   'base_url': settings.SITE_URL,
                   'pretty_date': pretty_date}

        send_mail_jinja(subject, 'ratings/emails/daily_digest.html',
                        context, recipient_list=author_emails,
                        perm_setting='app_new_review')
