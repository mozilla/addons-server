import datetime

from django.conf import settings
from django.db import models
from django.utils import translation

import bleach
import caching.base
import tower
from babel import Locale, numbers
from jinja2.filters import do_dictsort
from tower import ugettext as _

import amo
from amo.models import SearchMixin
from amo.fields import DecimalCharField
from amo.utils import get_locale_from_lang, send_mail_jinja
from zadmin.models import DownloadSource

from .db import StatsDictField


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


# TODO: remove when the script is proven to work correctly.
class DownloadCountTmp(StatsSearchMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    date = models.DateField()
    sources = StatsDictField(db_column='src', null=True)

    class Meta:
        db_table = 'download_counts_tmp'


class UpdateCount(StatsSearchMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    date = models.DateField()
    versions = StatsDictField(db_column='version', null=True)
    statuses = StatsDictField(db_column='status', null=True)
    applications = StatsDictField(db_column='application', null=True)
    oses = StatsDictField(db_column='os', null=True)
    locales = StatsDictField(db_column='locale', null=True)

    class Meta:
        db_table = 'update_counts'


# TODO: remove when the script is proven to work correctly.
class UpdateCountTmp(StatsSearchMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    date = models.DateField()
    versions = StatsDictField(db_column='version', null=True)
    statuses = StatsDictField(db_column='status', null=True)
    applications = StatsDictField(db_column='application', null=True)
    oses = StatsDictField(db_column='os', null=True)
    locales = StatsDictField(db_column='locale', null=True)

    class Meta:
        db_table = 'update_counts_tmp'


class ThemeUpdateCountManager(models.Manager):

    def get_last_x_days_avg(self, days):
        """Return a dict of the average number of users (count) over the last x
        days per addon."""
        today = datetime.date.today()
        averages = (self.values('addon_id')
                        .filter(date__gt=today - datetime.timedelta(days=days))
                        .annotate(avg=models.Avg('count')))
        # Transform the queryset from a list of dicts
        #   [{'addon_id': id1, 'count__avg': avg1], {'addon_id': id2, ...
        # to a dict
        #   {id1: avg1, id2: avg2, ...}
        return dict((d['addon_id'], d['avg']) for d in averages)


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


class AddonShareCount(models.Model):
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    service = models.CharField(max_length=255, null=True)
    date = models.DateField()

    class Meta:
        db_table = 'stats_share_counts'


class AddonShareCountTotal(models.Model):
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    service = models.CharField(max_length=255, null=True)

    class Meta:
        db_table = 'stats_share_counts_totals'


# stats_collections_share_counts exists too, but we don't touch it.
class CollectionShareCountTotal(models.Model):
    collection = models.ForeignKey('bandwagon.Collection')
    count = models.PositiveIntegerField()
    service = models.CharField(max_length=255, null=True)

    class Meta:
        db_table = 'stats_collections_share_counts_totals'


class ContributionError(Exception):

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class Contribution(amo.models.ModelBase):
    # TODO(addon): figure out what to do when we delete the add-on.
    addon = models.ForeignKey('addons.Addon')
    amount = DecimalCharField(max_digits=9, decimal_places=2,
                              nullify_invalid=True, null=True)
    currency = models.CharField(max_length=3,
                                choices=do_dictsort(amo.PAYPAL_CURRENCIES),
                                default=amo.CURRENCY_DEFAULT)
    source = models.CharField(max_length=255, null=True)
    client_data = models.ForeignKey('stats.ClientData', null=True)
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
    suggested_amount = DecimalCharField(max_digits=254, decimal_places=2,
                                        nullify_invalid=True, null=True)


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
        tower.activate(lang)
        return Locale(translation.to_locale(lang))

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
        else:
            try:
                author = self.addon.listed_authors[0]
                if author.email and not author.emailhidden:
                    from_email = author.email
            except (IndexError, TypeError):
                # This shouldn't happen, but the default set above is still ok.
                pass

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

    @staticmethod
    def post_save(sender, instance, **kwargs):
        from . import tasks
        tasks.addon_total_contributions.delay(instance.addon_id)

    def get_amount_locale(self, locale=None):
        """Localise the amount paid into the current locale."""
        if not locale:
            lang = translation.get_language()
            locale = get_locale_from_lang(lang)
        return numbers.format_currency(self.amount or 0,
                                       self.currency or 'USD',
                                       locale=locale)


models.signals.post_save.connect(Contribution.post_save, sender=Contribution)


class GlobalStat(caching.base.CachingMixin, models.Model):
    name = models.CharField(max_length=255)
    count = models.IntegerField()
    date = models.DateField()

    objects = caching.base.CachingManager()

    class Meta:
        db_table = 'global_stats'
        unique_together = ('name', 'date')
        get_latest_by = 'date'


class ClientData(models.Model):
    """
    Helps tracks user agent and download source data of installs and purchases.
    """
    download_source = models.ForeignKey('zadmin.DownloadSource', null=True)
    device_type = models.CharField(max_length=255)
    user_agent = models.CharField(max_length=255)
    is_chromeless = models.BooleanField(default=False)
    language = models.CharField(max_length=7)
    region = models.IntegerField(null=True)

    @classmethod
    def get_or_create(cls, request):
        """Get or create a client data object based on the current request."""
        download_source = request.REQUEST.get('src', '')
        try:
            download_source = DownloadSource.objects.get(name=download_source)
        except DownloadSource.DoesNotExist:
            download_source = None
        region = None
        if hasattr(request, 'LANG'):
            lang = request.LANG
        else:
            lang = translation.get_language()
        client_data, c = cls.objects.get_or_create(
            download_source=download_source,
            device_type=request.POST.get('device_type', ''),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            is_chromeless=request.POST.get('chromeless', False),
            language=lang,
            region=region)
        return client_data

    class Meta:
        db_table = 'client_data'
        unique_together = ('download_source', 'device_type', 'user_agent',
                           'is_chromeless', 'language', 'region')


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
