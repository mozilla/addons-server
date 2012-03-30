from datetime import datetime, timedelta

from django import http
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect

import commonware.log
import jingo
from tower import ugettext as _, ugettext_lazy as _lazy

from addons.views import BaseFilter
import amo
from amo.decorators import permission_required, post_required, write
from amo.utils import paginate
from market.models import PreApprovalUser
import paypal
from stats.models import Contribution
from translations.query import order_by_translation
from users.models import UserProfile
from users.tasks import delete_photo as delete_photo_task
from users.views import logout
from mkt.site import messages
from mkt.webapps.models import Webapp
from . import forms

log = commonware.log.getLogger('mkt.account')
paypal_log = commonware.log.getLogger('mkt.paypal')


def payment(request, status=None):
    # Note this is not post_required because PayPal does not reply with a
    # POST but a GET; that's a sad face.

    if status:
        pre, created = (PreApprovalUser.objects
                        .safer_get_or_create(user=request.amo_user))

        if status == 'complete':
            # The user has completed the setup at PayPal and bounced back.
            if 'setup-preapproval' in request.session:
                messages.success(request, _('Pre-approval set up'))
                paypal_log.info(u'Preapproval key created for user: %s'
                                % request.amo_user)
                data = request.session.get('setup-preapproval', {})
                pre.update(paypal_key=data.get('key'),
                           paypal_expiry=data.get('expiry'))
                del request.session['setup-preapproval']

        elif status == 'cancel':
            # The user has chosen to cancel out of PayPal. Nothing really
            # to do here; PayPal just bounces to this page.
            messages.success(request, _('Pre-approval changes cancelled'))

        elif status == 'remove':
            # The user has an pre approval key set and chooses to remove it.
            if pre.paypal_key:
                pre.update(paypal_key='')
                messages.success(request, _('Pre-approval removed'))
                paypal_log.info(u'Preapproval key removed for user: %s'
                                % request.amo_user)

        ctx = {'preapproval': pre}
    else:
        ctx = {'preapproval': request.amo_user.get_preapproval()}

    return jingo.render(request, 'account/payment.html', ctx)


@post_required
def preapproval(request):
    today = datetime.today()
    data = {'startDate': today,
            'endDate': today + timedelta(days=365 * 2),
            'pattern': 'account.payment'}
    try:
        result = paypal.get_preapproval_key(data)
    except paypal.PaypalError, e:
        paypal_log.error(u'Preapproval key: %s' % e, exc_info=True)
        raise

    paypal_log.info(u'Got preapproval key for user: %s' % request.amo_user)
    request.session['setup-preapproval'] = {
        'key': result['preapprovalKey'],
        'expiry': data['endDate'],
    }
    return redirect(paypal.get_preapproval_url(result['preapprovalKey']))


class PurchasesFilter(BaseFilter):
    opts = (('purchased', _lazy(u'Purchase Date')),
            ('price', _lazy(u'Price')),
            ('name', _lazy(u'Name')))

    def filter(self, field):
        qs = self.base_queryset
        if field == 'purchased':
            return (qs.filter(Q(addonpurchase__user=self.request.amo_user) |
                              Q(addonpurchase__isnull=True))
                    .order_by('-addonpurchase__created', 'id'))
        elif field == 'price':
            return qs.order_by('addonpremium__price__price', 'id')
        elif field == 'name':
            return order_by_translation(qs, 'name')


def purchases(request, product_id=None, template=None):
    """A list of purchases that a user has made through the Marketplace."""
    cs = (Contribution.objects
          .filter(user=request.amo_user,
                  type__in=[amo.CONTRIB_PURCHASE, amo.CONTRIB_REFUND,
                            amo.CONTRIB_CHARGEBACK])
          .order_by('created'))
    if product_id:
        cs = cs.filter(addon=product_id)

    ids = list(cs.values_list('addon_id', flat=True))
    # If you are asking for a receipt for just one item, show only that.
    # Otherwise, we'll show all apps that have a contribution or are free.
    if not product_id:
        ids += list(request.amo_user.installed_set
                    .exclude(addon__in=ids)
                    .values_list('addon_id', flat=True))

    contributions = {}
    for c in cs:
        contributions.setdefault(c.addon_id, []).append(c)

    ids = list(set(ids))
    listing = PurchasesFilter(request, Webapp.objects.filter(id__in=ids),
                              key='sort', default='purchased')

    if product_id and not listing.qs:
        # User has requested a receipt for an app he ain't got.
        raise http.Http404

    products = paginate(request, listing.qs, count=len(ids))
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
    form = forms.UserDeleteForm(request.POST, request=request)
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
