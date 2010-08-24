import datetime

from django.conf import settings
from django.db import models
from django.template import Context, loader

import caching.base
import tower
from tower import ugettext as _

from amo.models import ModelBase
from amo.fields import DecimalCharField
from amo.utils import send_mail as amo_send_mail

from .db import StatsDictField, StatsManager


class AddonCollectionCount(caching.base.CachingMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    collection = models.ForeignKey('bandwagon.Collection')
    count = models.PositiveIntegerField()
    date = models.DateField()

    class Meta:
        db_table = 'stats_addons_collections_counts'


class CollectionCount(caching.base.CachingMixin, models.Model):
    collection = models.ForeignKey('bandwagon.Collection')
    count = models.PositiveIntegerField()
    date = models.DateField()

    objects = models.Manager()
    stats = StatsManager('date')

    class Meta:
        db_table = 'stats_collections_counts'


class CollectionStats(caching.base.CachingMixin, models.Model):
    """In the running for worst-named model ever."""
    collection = models.ForeignKey('bandwagon.Collection')
    name = models.CharField(max_length=255, null=True)
    count = models.PositiveIntegerField()
    date = models.DateField()

    class Meta:
        db_table = 'stats_collections'


class DownloadCount(caching.base.CachingMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    date = models.DateField()

    # Leave this out of queries if you can.
    sources = StatsDictField(db_column='src', null=True)

    objects = models.Manager()
    stats = StatsManager('date')

    class Meta:
        db_table = 'download_counts'

    def flush_urls(self):
        return ['*/addon/%d/statistics/downloads*' % self.addon_id, ]


class UpdateCount(caching.base.CachingMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    date = models.DateField()

    # Leave these out of queries if you can.
    versions = StatsDictField(db_column='version', null=True)
    statuses = StatsDictField(db_column='status', null=True)
    applications = StatsDictField(db_column='application', null=True)
    oses = StatsDictField(db_column='os', null=True)
    locales = StatsDictField(db_column='locale', null=True)

    objects = models.Manager()
    stats = StatsManager('date')

    class Meta:
        db_table = 'update_counts'

    def flush_urls(self):
        return ['*/addon/%d/statistics/usage*' % self.addon_id, ]


class AddonShareCount(caching.base.CachingMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    service = models.CharField(max_length=255, null=True)
    date = models.DateField()

    objects = models.Manager()
    stats = StatsManager('date')

    class Meta:
        db_table = 'stats_share_counts'


class AddonShareCountTotal(caching.base.CachingMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    service = models.CharField(max_length=255, null=True)

    objects = caching.base.CachingManager()
    stats = caching.base.CachingManager()

    class Meta:
        db_table = 'stats_share_counts_totals'


# stats_collections_share_counts exists too, but we don't touch it.
class CollectionShareCountTotal(caching.base.CachingMixin, models.Model):
    collection = models.ForeignKey('bandwagon.Collection')
    count = models.PositiveIntegerField()
    service = models.CharField(max_length=255, null=True)

    objects = caching.base.CachingManager()

    class Meta:
        db_table = 'stats_collections_share_counts_totals'


class ContributionError(Exception):

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class Contribution(caching.base.CachingMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    amount = DecimalCharField(max_digits=9, decimal_places=2,
                              nullify_invalid=True, null=True)
    source = models.CharField(max_length=255, null=True)
    source_locale = models.CharField(max_length=10, null=True)
    annoying = models.BooleanField()
    created = models.DateTimeField(auto_now_add=True)
    uuid = models.CharField(max_length=255, null=True)
    is_suggested = models.BooleanField()
    suggested_amount = DecimalCharField(max_digits=254, decimal_places=2,
                                        nullify_invalid=True, null=True)
    comment = models.CharField(max_length=255)
    transaction_id = models.CharField(max_length=255, null=True)
    post_data = StatsDictField(null=True)

    objects = models.Manager()
    stats = StatsManager('created')

    class Meta:
        db_table = 'stats_contributions'

    def __unicode__(self):
        return u'%s: %s' % (self.addon.name, self.amount)

    def flush_urls(self):
        return ['*/addon/%d/statistics/contributions*' % self.addon_id, ]

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

    def mail_thankyou(self, request=None):
        """
        Mail a thankyou note for a completed contribution.

        Raises a ``ContributionError`` exception when the contribution
        is not complete or email addresses are not found.
        """

        # Setup l10n before loading addon.
        if self.source_locale:
            lang = self.source_locale
        else:
            lang = self.addon.default_locale
        tower.activate(lang)

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
        url_parts[1] = lang

        # Buildup the email components.
        t = loader.get_template('stats/contribution-thankyou-email.ltxt')
        c = {
            'thankyou_note': self.addon.thankyou_note,
            'addon_name': self.addon.name,
            'learn_url': '%s%s?src=emailinfo' % (settings.SITE_URL,
                                                 '/'.join(url_parts)),
            'domain': settings.DOMAIN,
        }
        body = t.render(Context(c))
        subject = _('Thanks for contributing to {addon_name}').format(
                    addon_name=self.addon.name)

        # Send the email
        if amo_send_mail(subject, body, from_email, [to_email],
                     fail_silently=True):
            # Clear out contributor identifying information.
            del(self.post_data['payer_email'])
            self.save()

    @staticmethod
    def post_save(sender, instance, **kwargs):
        from . import tasks
        tasks.addon_total_contributions.delay(instance.addon_id)


models.signals.post_save.connect(Contribution.post_save, sender=Contribution)


class SubscriptionEvent(ModelBase):
    """Save subscription info for future processing."""
    post_data = StatsDictField()

    class Meta:
        db_table = 'subscription_events'


class GlobalStat(caching.base.CachingMixin, models.Model):
    name = models.CharField(max_length=255)
    count = models.IntegerField()
    date = models.DateField()

    objects = caching.base.CachingManager()
    stats = caching.base.CachingManager()

    class Meta:
        db_table = 'global_stats'
        unique_together = ('name', 'date')
        get_latest_by = 'date'
