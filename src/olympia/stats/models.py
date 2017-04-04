import datetime

from django.conf import settings
from django.db import models
from django.utils.translation import (
    activate, to_locale, get_language, ugettext as _)

import bleach
import caching.base
from babel import Locale, numbers
from jinja2.filters import do_dictsort

from olympia import amo
from olympia.amo.models import SearchMixin
from olympia.amo.utils import get_locale_from_lang, send_mail_jinja

from .db import LargeStatsDictField, StatsDictField


def update_inc(initial, key, count):
    """Update or create a dict of `int` counters, for StatsDictFields."""
    initial = initial or {}
    initial[key] = count + initial.get(key, 0)
    return initial


class AddonCollectionCount(models.Model):
    addon = models.ForeignKey('addons.Addon')
    collection = models.ForeignKey('bandwagon.Collection')
    count = models.PositiveIntegerField()
    date = models.DateField()

    class Meta:
        db_table = 'stats_addons_collections_counts'


class StatsSearchMixin(SearchMixin):

    ES_ALIAS_KEY = 'stats'


class CollectionCount(StatsSearchMixin, models.Model):
    collection = models.ForeignKey('bandwagon.Collection')
    count = models.PositiveIntegerField()
    date = models.DateField()

    class Meta:
        db_table = 'stats_collections_counts'


class CollectionStats(models.Model):
    """In the running for worst-named model ever."""
    collection = models.ForeignKey('bandwagon.Collection')
    name = models.CharField(max_length=255, null=True)
    count = models.PositiveIntegerField()
    date = models.DateField()

    class Meta:
        db_table = 'stats_collections'


class DownloadCount(StatsSearchMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    date = models.DateField()
    sources = StatsDictField(db_column='src', null=True)

    class Meta:
        db_table = 'download_counts'


class UpdateCount(StatsSearchMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    date = models.DateField()
    versions = StatsDictField(db_column='version', null=True)
    statuses = StatsDictField(db_column='status', null=True)
    applications = LargeStatsDictField(db_column='application', null=True)
    oses = StatsDictField(db_column='os', null=True)
    locales = StatsDictField(db_column='locale', null=True)

    class Meta:
        db_table = 'update_counts'


class ThemeUpdateCountManager(models.Manager):

    def get_range_days_avg(self, start, end, *extra_fields):
        """Return a a ValuesListQuerySet containing the addon_id and popularity
        for each theme where popularity is the average number of users (count)
        over the given range of days passed as start / end arguments.

        If extra_fields are passed, then the list of fields is returned in the
        queryset, inserted after addon_id but before popularity."""
        return (self.values_list('addon_id', *extra_fields)
                    .filter(date__range=[start, end])
                    .annotate(avg=models.Avg('count')))


class ThemeUpdateCount(StatsSearchMixin, models.Model):
    """Daily users taken from the ADI data (coming from Hive)."""
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    date = models.DateField()

    objects = ThemeUpdateCountManager()

    class Meta:
        db_table = 'theme_update_counts'


class ThemeUpdateCountBulk(models.Model):
    """Used by the update_theme_popularity_movers command for perf reasons.

    First bulk inserting all the averages over the last week and last three
    weeks in this table allows us to bulk update (instead of running an update
    per Persona).

    """
    persona_id = models.PositiveIntegerField()
    popularity = models.PositiveIntegerField()
    movers = models.FloatField()

    class Meta:
        db_table = 'theme_update_counts_bulk'


class ContributionError(Exception):

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class Contribution(amo.models.ModelBase):
    # TODO(addon): figure out what to do when we delete the add-on.
    addon = models.ForeignKey('addons.Addon')
    amount = models.DecimalField(max_digits=9, decimal_places=2, null=True)
    currency = models.CharField(max_length=3,
                                choices=do_dictsort(amo.PAYPAL_CURRENCIES),
                                default=amo.CURRENCY_DEFAULT)
    source = models.CharField(max_length=255, null=True)
    source_locale = models.CharField(max_length=10, null=True)
    # This is the external id that you can communicate to the world.
    uuid = models.CharField(max_length=255, null=True, db_index=True)
    comment = models.CharField(max_length=255)
    # This is the internal transaction id between us and a provider,
    # for example paypal or solitude.
    transaction_id = models.CharField(max_length=255, null=True, db_index=True)
    paykey = models.CharField(max_length=255, null=True)
    post_data = StatsDictField(null=True)

    # Voluntary Contribution specific.
    charity = models.ForeignKey('addons.Charity', null=True)
    annoying = models.PositiveIntegerField(default=0,
                                           choices=amo.CONTRIB_CHOICES,)
    is_suggested = models.BooleanField(default=False)
    suggested_amount = models.DecimalField(max_digits=9, decimal_places=2,
                                           null=True)

    class Meta:
        db_table = 'stats_contributions'

    def __unicode__(self):
        return u'%s: %s' % (self.addon.name, self.amount)

    @property
    def date(self):
        try:
            return datetime.date(self.created.year,
                                 self.created.month, self.created.day)
        except AttributeError:
            # created may be None
            return None

    @property
    def contributor(self):
        try:
            return u'%s %s' % (self.post_data['first_name'],
                               self.post_data['last_name'])
        except (TypeError, KeyError):
            # post_data may be None or missing a key
            return None

    @property
    def email(self):
        try:
            return self.post_data['payer_email']
        except (TypeError, KeyError):
            # post_data may be None or missing a key
            return None

    def _switch_locale(self):
        if self.source_locale:
            lang = self.source_locale
        else:
            lang = self.addon.default_locale
        activate(lang)
        return Locale(to_locale(lang))

    def mail_thankyou(self, request=None):
        """
        Mail a thankyou note for a completed contribution.

        Raises a ``ContributionError`` exception when the contribution
        is not complete or email addresses are not found.
        """
        locale = self._switch_locale()

        # Thankyous must be enabled.
        if not self.addon.enable_thankyou:
            # Not an error condition, just return.
            return

        # Contribution must be complete.
        if not self.transaction_id:
            raise ContributionError('Transaction not complete')

        # Send from support_email, developer's email, or default.
        from_email = settings.DEFAULT_FROM_EMAIL
        if self.addon.support_email:
            from_email = str(self.addon.support_email)

        # We need the contributor's email.
        to_email = self.post_data['payer_email']
        if not to_email:
            raise ContributionError('Empty payer email')

        # Make sure the url uses the right language.
        # Setting a prefixer would be nicer, but that requires a request.
        url_parts = self.addon.meet_the_dev_url().split('/')
        url_parts[1] = locale.language

        subject = _('Thanks for contributing to {addon_name}').format(
            addon_name=self.addon.name)

        # Send the email.
        send_mail_jinja(
            subject, 'stats/contribution-thankyou-email.ltxt',
            {'thankyou_note': bleach.clean(unicode(self.addon.thankyou_note),
                                           strip=True),
             'addon_name': self.addon.name,
             'learn_url': '%s%s?src=emailinfo' % (settings.SITE_URL,
                                                  '/'.join(url_parts)),
             'domain': settings.DOMAIN},
            from_email, [to_email], fail_silently=True,
            perm_setting='dev_thanks')

    def get_amount_locale(self, locale=None):
        """Localise the amount paid into the current locale."""
        if not locale:
            lang = get_language()
            locale = get_locale_from_lang(lang)
        return numbers.format_currency(self.amount or 0,
                                       self.currency or 'USD',
                                       locale=locale)


class GlobalStat(caching.base.CachingMixin, models.Model):
    name = models.CharField(max_length=255)
    count = models.IntegerField()
    date = models.DateField()

    objects = caching.base.CachingManager()

    class Meta:
        db_table = 'global_stats'
        unique_together = ('name', 'date')
        get_latest_by = 'date'


class ThemeUserCount(StatsSearchMixin, models.Model):
    """Theme popularity (weekly average of users).

    This is filled in by a cron job reading the popularity from the theme
    (Persona).

    """
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    date = models.DateField()

    class Meta:
        db_table = 'theme_user_counts'
