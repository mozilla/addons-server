import datetime

from django.conf import settings
from django.db import models
from django.template import Context, loader
from django.utils import translation

from babel import Locale, numbers
import caching.base
from jingo import env
from jinja2.filters import do_dictsort
import tower
from tower import ugettext as _

import amo
from amo.helpers import absolutify, urlparams
from amo.models import SearchMixin
from amo.fields import DecimalCharField
from amo.utils import send_mail, send_mail_jinja
from zadmin.models import DownloadSource

from .db import StatsDictField


class AddonCollectionCount(models.Model):
    addon = models.ForeignKey('addons.Addon')
    collection = models.ForeignKey('bandwagon.Collection')
    count = models.PositiveIntegerField()
    date = models.DateField()

    class Meta:
        db_table = 'stats_addons_collections_counts'


class CollectionCount(SearchMixin, models.Model):
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


class DownloadCount(SearchMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    date = models.DateField()
    sources = StatsDictField(db_column='src', null=True)

    class Meta:
        db_table = 'download_counts'


class UpdateCount(SearchMixin, models.Model):
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
    is_suggested = models.BooleanField()
    suggested_amount = DecimalCharField(max_digits=254, decimal_places=2,
                                        nullify_invalid=True, null=True)

    # Marketplace specific.
    # TODO(andym): figure out what to do when we delete the user.
    user = models.ForeignKey('users.UserProfile', blank=True, null=True)
    type = models.PositiveIntegerField(default=amo.CONTRIB_TYPE_DEFAULT,
                                       choices=do_dictsort(amo.CONTRIB_TYPES))
    price_tier = models.ForeignKey('market.Price', blank=True, null=True,
                                   on_delete=models.PROTECT)
    # If this is a refund or a chargeback, which charge did it relate to.
    related = models.ForeignKey('self', blank=True, null=True,
                                on_delete=models.PROTECT)

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

    def handle_chargeback(self, reason):
        """
        Hook to handle a payment chargeback.

        When a chargeback is received from a PayPal IPN
        for this contribution, the hook is called.

        reason is either 'reversal' or 'refund'
        """
        # Sigh. AMO does not have inapp_pay installed and it does not have
        # the database tables. Since both mkt and AMO share this code we
        # need to hide it from AMO.
        if ('mkt.inapp_pay' in settings.INSTALLED_APPS
            and self.inapp_payment.count()):
            self.inapp_payment.get().handle_chargeback(reason)

    def _switch_locale(self):
        if self.source_locale:
            lang = self.source_locale
        else:
            lang = self.addon.default_locale
        tower.activate(lang)
        return Locale(translation.to_locale(lang))

    def _mail(self, template, subject, context):
        template = env.get_template(template)
        body = template.render(context)
        send_mail(subject, body, settings.MARKETPLACE_EMAIL,
                  [self.user.email], fail_silently=True)

    def mail_chargeback(self):
        """Send to the purchaser of an add-on about reversal from Paypal."""
        locale = self._switch_locale()
        amt = numbers.format_currency(abs(self.amount), self.currency,
                                      locale=locale)
        self._mail('users/support/emails/chargeback.txt',
                   # L10n: the adddon name.
                   _(u'%s payment reversal' % self.addon.name),
                   {'name': self.addon.name, 'amount': amt})

    def record_failed_refund(self, e, user):
        self.enqueue_refund(amo.REFUND_FAILED, user,
                            rejection_reason=str(e))
        self._switch_locale()
        self._mail('users/support/emails/refund-failed.txt',
                   # L10n: the addon name.
                   _(u'%s refund failed' % self.addon.name),
                   {'name': self.addon.name})
        send_mail_jinja(
            'Refund failed', 'devhub/email/refund-failed.txt',
            {'name': self.user.email,
             'error': str(e)},
            settings.MARKETPLACE_EMAIL,
            [str(self.addon.support_email)], fail_silently=True)

    def mail_approved(self):
        """The developer has approved a refund."""
        locale = self._switch_locale()
        amt = numbers.format_currency(abs(self.amount), self.currency,
                                      locale=locale)
        self._mail('users/support/emails/refund-approved.txt',
                   # L10n: the adddon name.
                   _(u'%s refund approved' % self.addon.name),
                   {'name': self.addon.name, 'amount': amt})

    def mail_declined(self):
        """The developer has declined a refund."""
        self._switch_locale()
        self._mail('users/support/emails/refund-declined.txt',
                   # L10n: the adddon name.
                   _(u'%s refund declined' % self.addon.name),
                   {'name': self.addon.name})

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
        if send_mail(subject, body, from_email, [to_email],
                     fail_silently=True, perm_setting='dev_thanks'):
            # Clear out contributor identifying information.
            del(self.post_data['payer_email'])
            self.save()

    def enqueue_refund(self, status, user, refund_reason=None,
                       rejection_reason=None):
        """Keep track of a contribution's refund status."""
        from market.models import Refund
        refund, c = Refund.objects.safer_get_or_create(contribution=self,
                                                       user=user)
        refund.status = status

        # Determine which timestamps to update.
        timestamps = []
        if status in (amo.REFUND_PENDING, amo.REFUND_APPROVED_INSTANT,
                      amo.REFUND_FAILED):
            timestamps.append('requested')
        if status in (amo.REFUND_APPROVED, amo.REFUND_APPROVED_INSTANT):
            timestamps.append('approved')
        elif status == amo.REFUND_DECLINED:
            timestamps.append('declined')
        for ts in timestamps:
            setattr(refund, ts, datetime.datetime.now())

        if refund_reason:
            refund.refund_reason = refund_reason
        if rejection_reason:
            refund.rejection_reason = rejection_reason
        refund.save()
        return refund

    @staticmethod
    def post_save(sender, instance, **kwargs):
        from . import tasks
        tasks.addon_total_contributions.delay(instance.addon_id)

    def get_amount_locale(self, locale=None):
        """Localise the amount paid into the current locale."""
        if not locale:
            lang = translation.get_language()
            locale = Locale(translation.to_locale(lang))
        return numbers.format_currency(self.amount or 0,
                                       self.currency or 'USD',
                                       locale=locale)

    def get_refund_url(self):
        return urlparams(self.addon.get_dev_url('issue_refund'),
                         transaction_id=self.transaction_id)

    def get_absolute_refund_url(self):
        return absolutify(self.get_refund_url())

    def is_instant_refund(self, period=settings.PAYPAL_REFUND_INSTANT):
        if self.type != amo.CONTRIB_PURCHASE:
            return False
        limit = datetime.timedelta(seconds=period)
        return datetime.datetime.now() < (self.created + limit)

    def get_refund_contribs(self):
        """Get related set of refund contributions."""
        return Contribution.objects.filter(
            related=self, type=amo.CONTRIB_REFUND).order_by('-modified')

    def is_refunded(self):
        """
        If related has been set, then this transaction has been refunded or
        charged back. This is a bit expensive, so refrain from using on listing
        pages.
        """
        return (Contribution.objects.filter(related=self,
                                            type__in=[amo.CONTRIB_REFUND,
                                                      amo.CONTRIB_CHARGEBACK])
                                    .exists())


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
    is_chromeless = models.BooleanField()
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
        if settings.MARKETPLACE:
            import mkt
            if hasattr(request, 'REGION') and request.REGION:
                region = request.REGION.id
            else:
                region = mkt.regions.WORLDWIDE.id
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
