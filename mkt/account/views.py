from datetime import datetime, timedelta

from django import http
from django.shortcuts import get_object_or_404, redirect

import commonware.log
import jingo
from tower import ugettext as _, ugettext_lazy as _lazy

from access import acl
from addons.views import BaseFilter
import amo
from amo.decorators import (login_required, permission_required, post_required,
                            write)
from amo.models import manual_order
from amo.urlresolvers import reverse
from amo.utils import paginate
from market.models import PreApprovalUser
import paypal
from stats.models import Contribution
from translations.query import order_by_translation
from users.models import UserProfile
from users.tasks import delete_photo as delete_photo_task
from users.views import logout
from mkt.account.forms import CurrencyForm
from mkt.site import messages
from mkt.webapps.models import Webapp
from . import forms

log = commonware.log.getLogger('mkt.account')
paypal_log = commonware.log.getLogger('mkt.paypal')


@login_required
def payment(request, status=None):
    # Note this is not post required, because PayPal does not reply with a
    # POST but a GET, that's a sad face.
    pre, created = (PreApprovalUser.objects
                        .safer_get_or_create(user=request.amo_user))
    if status:
        data = request.session.get('setup-preapproval', {})

        if status == 'complete':
            # The user has completed the setup at PayPal and bounced back.
            if 'setup-preapproval' in request.session:
                paypal_log.info(u'Preapproval key created for user: %s'
                                % request.amo_user)
                pre.update(paypal_key=data.get('key'),
                           paypal_expiry=data.get('expiry'))

                # If there is a target, bounce to it and don't show a message
                # we'll let whatever set this up worry about that.
                if data.get('complete'):
                    return redirect(data['complete'])

                messages.success(request, _('Wallet set up.'))
                del request.session['setup-preapproval']

        elif status == 'cancel':
            # The user has chosen to cancel out of PayPal. Nothing really
            # to do here, PayPal just bounce to the cancel page if defined.
            if data.get('cancel'):
                return redirect(data['cancel'])

            messages.success(request, _('Wallet changes cancelled.'))

        elif status == 'remove':
            # The user has an pre approval key set and chooses to remove it
            if pre.paypal_key:
                pre.update(paypal_key='')
                messages.success(request, _('Wallet removed.'))
                paypal_log.info(u'Preapproval key removed for user: %s'
                                % request.amo_user)

        context = {'preapproval': pre}
    else:
        context = {'preapproval': request.amo_user.get_preapproval()}

    context['currency'] = CurrencyForm(initial={'currency':
                                                pre.currency or 'USD'})
    return jingo.render(request, 'account/payment.html', context)


@post_required
@login_required
def currency(request, do_redirect=True):
    pre, created = (PreApprovalUser.objects
                        .safer_get_or_create(user=request.amo_user))
    currency = CurrencyForm(request.POST or {},
                            initial={'currency': pre.currency or 'USD'})
    if currency.is_valid():
        pre.update(currency=currency.cleaned_data['currency'])
        if do_redirect:
            messages.success(request, _('Currency saved.'))
            return redirect(reverse('account.payment'))
    else:
        return jingo.render(request, 'account/payment.html',
                            {'preapproval': pre,
                             'currency': currency})


@post_required
@login_required
def preapproval(request, complete=None, cancel=None):
    failure = currency(request, do_redirect=False)
    if failure:
        return failure

    today = datetime.today()
    data = {'startDate': today,
            'endDate': today + timedelta(days=365),
            'pattern': 'account.payment',
            }
    try:
        result = paypal.get_preapproval_key(data)
    except paypal.PaypalError, e:
        paypal_log.error(u'Preapproval key: %s' % e, exc_info=True)
        raise

    paypal_log.info(u'Got preapproval key for user: %s' % request.amo_user.pk)
    request.session['setup-preapproval'] = {
        'key': result['preapprovalKey'],
        'expiry': data['endDate'],
        'complete': complete,
        'cancel': cancel
    }
    return redirect(paypal.get_preapproval_url(result['preapprovalKey']))


class PurchasesFilter(BaseFilter):
    opts = (('purchased', _lazy(u'Purchase Date')),
            ('price', _lazy(u'Price')),
            ('name', _lazy(u'Name')))

    def __init__(self, *args, **kwargs):
        self.ids = kwargs.pop('ids')
        self.uids = kwargs.pop('uids')
        super(PurchasesFilter, self).__init__(*args, **kwargs)

    def filter(self, field):
        qs = self.base_queryset
        if field == 'purchased':
            # Id's are in created order, so let's invert them for this query.
            # According to my testing we don't actually need to dedupe this.
            ids = list(reversed(self.ids[0])) + self.ids[1]
            return manual_order(qs.filter(id__in=ids), ids)
        elif field == 'price':
            return (qs.filter(id__in=self.uids)
                      .order_by('addonpremium__price__price', 'id'))
        elif field == 'name':
            return order_by_translation(qs.filter(id__in=self.uids), 'name')


def purchases(request, product_id=None, template=None):
    """A list of purchases that a user has made through the Marketplace."""
    cs = (Contribution.objects
          .filter(user=request.amo_user,
                  type__in=[amo.CONTRIB_PURCHASE, amo.CONTRIB_INAPP,
                            amo.CONTRIB_REFUND, amo.CONTRIB_CHARGEBACK])
          .order_by('created'))
    if product_id:
        cs = cs.filter(addon=product_id)

    ids = list(cs.values_list('addon_id', flat=True))
    product_ids = []
    # If you are asking for a receipt for just one item, show only that.
    # Otherwise, we'll show all apps that have a contribution or are free.
    if not product_id:
        product_ids = list(request.amo_user.installed_set
                           .exclude(addon__in=ids)
                           .values_list('addon_id', flat=True))

    contributions = {}
    for c in cs:
        contributions.setdefault(c.addon_id, []).append(c)

    unique_ids = set(ids + product_ids)
    listing = PurchasesFilter(request, Webapp.objects.all(),
                              key='sort', default='purchased',
                              ids=[ids, product_ids],
                              uids=unique_ids)

    if product_id and not listing.qs:
        # User has requested a receipt for an app he ain't got.
        raise http.Http404

    products = paginate(request, listing.qs, count=len(unique_ids))
    return jingo.render(request, 'account/purchases.html',
                        {'pager': products,
                         'listing_filter': listing,
                         'contributions': contributions,
                         'single': bool(product_id)})


@write
def account_settings(request):
    # Don't use `request.amo_user` because it's too cached.
    amo_user = request.amo_user.user.get_profile()
    form = forms.UserEditForm(request.POST or None, request.FILES or None,
                              request=request, instance=amo_user)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, _('Profile Updated'))
            return redirect('account.settings')
        else:
            messages.form_errors(request)
    return jingo.render(request, 'account/settings.html',
                        {'form': form, 'amouser': amo_user})


@write
@login_required
@permission_required('Users', 'Edit')
def admin_edit(request, user_id):
    amouser = get_object_or_404(UserProfile, pk=user_id)
    form = forms.AdminUserEditForm(request.POST or None, request.FILES or None,
                                   request=request, instance=amouser)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, _('Profile Updated'))
        return redirect('zadmin.index')
    return jingo.render(request, 'account/settings.html',
                        {'form': form, 'amouser': amouser})


def delete(request):
    amouser = request.amo_user
    form = forms.UserDeleteForm(request.POST or None, request=request)
    if request.method == 'POST' and form.is_valid():
        messages.success(request, _('Profile Deleted'))
        amouser.anonymize()
        logout(request)
        form = None
        return redirect('users.login')
    return jingo.render(request, 'account/delete.html',
                        {'form': form, 'amouser': amouser})


@post_required
def delete_photo(request):
    request.amo_user.update(picture_type='')
    delete_photo_task.delay(request.amo_user.picture_path)
    log.debug(u'User (%s) deleted photo' % request.amo_user)
    messages.success(request, _('Photo Deleted'))
    return http.HttpResponse()


def profile(request, username):
    if username.isdigit():
        user = get_object_or_404(UserProfile, id=username)
    else:
        user = get_object_or_404(UserProfile, username=username)

    edit_any_user = acl.action_allowed(request, 'Users', 'Edit')
    own_profile = (request.user.is_authenticated() and
                   request.amo_user.id == user.id)

    submissions = []
    if user.is_developer:
        submissions = paginate(request,
                               user.apps_listed.order_by('-weekly_downloads'),
                               per_page=5)

    data = {'profile': user, 'edit_any_user': edit_any_user,
            'submissions': submissions, 'own_profile': own_profile}

    return jingo.render(request, 'account/profile.html', data)
