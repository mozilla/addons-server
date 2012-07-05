from smtplib import SMTPRecipientsRefused

from django import http
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect
from django.utils.datastructures import SortedDict
from django.utils.decorators import method_decorator
from django.utils.encoding import smart_str, smart_unicode

import commonware.log
import jingo
from radagast.wizard import Wizard
from tower import ugettext as _, ugettext_lazy as _lazy
import waffle
from waffle.decorators import waffle_switch

import amo
from amo.decorators import login_required
from amo.urlresolvers import reverse
from amo.utils import send_mail_jinja
from lib.pay_server import client
import paypal
from paypal import PaypalError
from mkt.site import messages
from stats.models import Contribution
from . import forms

log = commonware.log.getLogger('z.support')
paypal_log = commonware.log.getLogger('z.paypal')


def support_mail(subject, template, context, sender, recipients):
    try:
        return send_mail_jinja(subject, template, context, from_email=sender,
                               recipient_list=recipients)
    except SMTPRecipientsRefused, e:
        log.error('Tried to send mail from %s to %s: %s' %
                  (sender, ', '.join(recipients), e), exc_info=True)


# Start of the Support wizard all of these are accessed through the
# SupportWizard below.
def plain(request, contribution, wizard):
    # Simple view that just shows a template matching the step.
    tpl = wizard.tpl('%s.html' % wizard.step)
    return wizard.render(request, tpl,
                         {'product': contribution.addon,
                          'contribution': contribution})


def support_resources(request, contribution, wizard):
    return wizard.render(request, wizard.tpl('resources.html'),
                         {'contribution': contribution,
                          'title': _('Helpful Resources')})


def support_author(request, contribution, wizard):
    addon = contribution.addon
    form = forms.ContactForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        context = {'contribution': contribution, 'product': addon,
                   'form': form, 'user': request.amo_user, 'request': request}
        log.info('Support request to dev. by user: %s for addon: %s' %
                 (request.amo_user.pk, addon.pk))

        # L10n: %s is the app name.
        support_mail(_(u'New Support Request for %s' % addon.name),
                     wizard.tpl('emails/support-request.txt'), context,
                     request.amo_user.email, [smart_str(addon.support_email)])

        return redirect(reverse('support',
                         args=[contribution.pk, 'author-sent']))
    return wizard.render(request, wizard.tpl('author.html'),
                         {'product': addon, 'contribution': contribution,
                          'form': form, 'title': _('Contact the Author')})


def support_mozilla(request, contribution, wizard):
    addon = contribution.addon
    form = forms.ContactForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        context = {'product': addon, 'form': form,
                   'contribution': contribution, 'user': request.amo_user,
                   'request': request}
        log.info('Support request to mozilla by user: %s for addon: %s' %
                 (request.amo_user.pk, addon.pk))

        # L10n: %s is the app name.
        support_mail(_(u'New Support Request for %s' % addon.name),
                     wizard.tpl('emails/support-request.txt'), context,
                     request.amo_user.email, [settings.MARKETPLACE_EMAIL])

        return redirect(reverse('support',
                                args=[contribution.pk, 'mozilla-sent']))
    return wizard.render(request, wizard.tpl('mozilla.html'),
                         {'product': addon, 'contribution': contribution,
                          'form': form, 'title': _('Contact Mozilla')})


@waffle_switch('allow-refund')
def refund_request(request, contribution, wizard):
    addon = contribution.addon
    if request.method == 'POST':
        return redirect('support', contribution.pk, 'reason')
    return wizard.render(request, wizard.tpl('request.html'),
                         {'product': addon, 'contribution': contribution,
                          'title': _('Request Refund')})


@waffle_switch('allow-refund')
def refund_reason(request, contribution, wizard):
    addon = contribution.addon
    if not 'request' in wizard.get_progress():
        return redirect('support', contribution.pk, 'request')

    if contribution.transaction_id is None:
        messages.error(request,
            _('A refund cannot be applied for yet. Please try again later. '
              'If this error persists contact apps-marketplace@mozilla.org.'))
        paypal_log.info('Refund requested for contribution with no '
                        'transaction_id: %r' % contribution.pk)
        return redirect('account.purchases')

    if contribution.is_refunded():
        messages.error(request, _('This has already been refunded.'))
        paypal_log.info('Already refunded: %s' % contribution.pk)
        return redirect('account.purchases')

    if contribution.is_instant_refund():
        if waffle.flag_is_active(request, 'solitude-payments'):
            try:
                client.post_refund(data={'uuid': contribution.transaction_id})
            except client.Error, e:
                paypal_log.error('Paypal error with refund', exc_info=True)
                messages.error(request, _('There was an error with your '
                                          'instant refund.'))
                contribution.record_failed_refund(e)
                return redirect('account.purchases')
        else:
            # TODO(solitude): remove this.
            try:
                paypal.refund(contribution.paykey)
            except PaypalError, e:
                paypal_log.error('Paypal error with refund', exc_info=True)
                messages.error(request, _('There was an error with your '
                                          'instant refund.'))
                contribution.record_failed_refund(e)
                return redirect('account.purchases')

        refund = contribution.enqueue_refund(amo.REFUND_APPROVED_INSTANT)
        paypal_log.info('Refund %r issued for contribution %r' %
                        (refund.pk, contribution.pk))
        # Note: we have to wait for PayPal to issue an IPN before it's
        # completely refunded.
        messages.success(request, _('Refund is being processed.'))
        amo.log(amo.LOG.REFUND_INSTANT, addon)
        return redirect('account.purchases')

    form = forms.ContactForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        reason = form.cleaned_data['text']
        context = {'product': addon,
                   'form': form,
                   'user': request.amo_user,
                   'contribution': contribution,
                   'refund_url': contribution.get_absolute_refund_url(),
                   'refund_reason': reason,
                   'request': request}
        log.info('Refund request sent by user: %s for addon: %s' %
                 (request.amo_user.pk, addon.pk))

        # L10n: %s is the app name.
        support_mail(_(u'New Refund Request for %s' % addon.name),
                     wizard.tpl('emails/refund-request.txt'), context,
                     settings.NOBODY_EMAIL, [smart_str(addon.support_email)])

        # Add this refund request to the queue.
        contribution.enqueue_refund(amo.REFUND_PENDING, reason)
        amo.log(amo.LOG.REFUND_REQUESTED, addon)
        return redirect(reverse('support',
                                args=[contribution.pk, 'refund-sent']))

    return wizard.render(request, wizard.tpl('refund.html'),
                         {'product': addon, 'contribution': contribution,
                          'form': form, 'title': _('Request Refund')})


class SupportWizard(Wizard):
    title = _lazy('Support')
    steps = SortedDict([('start', plain),
                        ('site', plain),
                        ('resources', support_resources),
                        ('mozilla', support_mozilla),
                        ('mozilla-sent', plain),
                        ('author', support_author),
                        ('author-sent', plain),
                        ('request', refund_request),
                        ('reason', refund_reason),
                        ('refund-sent', plain)])

    def tpl(self, x):
        return 'support/%s' % x

    @property
    def wrapper(self):
        return self.tpl('wrapper.html')

    @method_decorator(login_required)
    def dispatch(self, request, contribution_id, step='', *args, **kw):
        contribution = get_object_or_404(Contribution, pk=contribution_id)
        if contribution.user.pk != request.amo_user.pk:
            raise http.Http404
        args = [contribution] + list(args)
        return super(SupportWizard, self).dispatch(request, step, *args, **kw)

    def render(self, request, template, context):
        new_title = []

        title = context.get('title')
        if title:
            new_title.append(title)
        else:
            new_title.append(unicode(self.title))

        product = context.get('product')
        if product:
            new_title.append(smart_unicode(product.name))
        else:
            new_title.append(unicode(self.title))

        self.title = ' | '.join(new_title)

        # Skip AJAX stuff.
        context.update(wizard=self, content=template)
        return jingo.render(request, self.wrapper, context)
