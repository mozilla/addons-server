import collections
import functools
import json
import os
import sys
import time
import traceback
import uuid

from django import http
from django.core.files.storage import default_storage as storage
from django.conf import settings
from django import forms as django_forms
from django.db import models, transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import urlquote
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_view_exempt

import commonware.log
import jingo
from PIL import Image
from session_csrf import anonymous_csrf
from tower import ugettext_lazy as _lazy, ugettext as _
import waffle
from waffle.decorators import waffle_switch

from applications.models import Application, AppVersion
import amo
import amo.utils
from amo import messages
from amo.decorators import json_view, login_required, post_required, write
from amo.helpers import loc, urlparams
from amo.utils import escape_all, HttpResponseSendFile, MenuItem
from amo.urlresolvers import reverse
from access import acl
from addons import forms as addon_forms
from addons.decorators import addon_view, can_become_premium
from addons.models import Addon, AddonUser
from addons.views import BaseFilter
from devhub.decorators import dev_required
from devhub.forms import CheckCompatibilityForm
from devhub.models import ActivityLog, BlogPost, RssKey, SubmitStep
from devhub import perf
from editors.helpers import get_position
from files.models import File, FileUpload, Platform
from files.utils import parse_addon
from market.models import AddonPremium, Refund
from paypal.check import Check
import paypal
from search.views import BaseAjaxSearch
from stats.models import Contribution
from translations.models import delete_translation
from users.models import UserProfile
from versions.models import Version
from mkt.webapps.models import Webapp
from zadmin.models import ValidationResult

from . import forms, tasks, feeds, signals

log = commonware.log.getLogger('z.devhub')
paypal_log = commonware.log.getLogger('z.paypal')


# We use a session cookie to make sure people see the dev agreement.
DEV_AGREEMENT_COOKIE = 'yes-I-read-the-dev-agreement'


class AddonFilter(BaseFilter):
    opts = (('name', _lazy(u'Name')),
            ('updated', _lazy(u'Updated')),
            ('created', _lazy(u'Created')),
            ('popular', _lazy(u'Downloads')),
            ('rating', _lazy(u'Rating')))


class AppFilter(BaseFilter):
    opts = (('name', _lazy(u'Name')),
            ('created', _lazy(u'Created')),
            ('downloads', _lazy(u'Weekly Downloads')),
            ('rating', _lazy(u'Rating')))


def addon_listing(request, default='name', webapp=False):
    """Set up the queryset and filtering for addon listing for Dashboard."""
    Filter = AppFilter if webapp else AddonFilter
    if webapp:
        qs = Webapp.objects.filter(
            id__in=request.amo_user.addons.filter(type=amo.ADDON_WEBAPP))
        model = Webapp
    else:
        qs = request.amo_user.addons.exclude(type=amo.ADDON_WEBAPP)
        model = Addon
    filter = Filter(request, qs, 'sort', default, model=model)
    return filter.qs, filter


def index(request):
    if settings.APP_PREVIEW:
        # This can be a permanent redirect when we finalize devhub for apps.
        return redirect('devhub.apps')

    ctx = {'blog_posts': _get_posts()}
    if request.amo_user:
        user_addons = request.amo_user.addons.exclude(type=amo.ADDON_WEBAPP)
        recent_addons = user_addons.order_by('-modified')[:3]
        ctx['recent_addons'] = []
        for addon in recent_addons:
            ctx['recent_addons'].append({'addon': addon,
                                         'position': get_position(addon)})

    return jingo.render(request, 'devhub/index.html', ctx)


@login_required
def dashboard(request, webapp=False):
    addons, filter = addon_listing(request, webapp=webapp)
    addons = amo.utils.paginate(request, addons, per_page=10)
    blog_posts = _get_posts()
    all_addons = request.amo_user.addons.exclude(type=amo.ADDON_WEBAPP)
    data = dict(addons=addons, sorting=filter.field, filter=filter,
                items=_get_items(None, all_addons)[:4],
                sort_opts=filter.opts, rss=_get_rss_feed(request),
                blog_posts=blog_posts, timestamp=int(time.time()),
                webapp=webapp)
    return jingo.render(request, 'devhub/addons/dashboard.html', data)


@dev_required
def ajax_compat_status(request, addon_id, addon):
    if not (addon.accepts_compatible_apps() and addon.current_version):
        raise http.Http404()
    return jingo.render(request, 'devhub/addons/ajax_compat_status.html',
                        dict(addon=addon))


@dev_required
def ajax_compat_error(request, addon_id, addon):
    if not (addon.accepts_compatible_apps() and addon.current_version):
        raise http.Http404()
    return jingo.render(request, 'devhub/addons/ajax_compat_error.html',
                        dict(addon=addon))


@dev_required
def ajax_compat_update(request, addon_id, addon, version_id):
    if not addon.accepts_compatible_apps():
        raise http.Http404()
    version = get_object_or_404(Version, pk=version_id, addon=addon)
    compat_form = forms.CompatFormSet(request.POST or None,
                                      queryset=version.apps.all())
    if request.method == 'POST' and compat_form.is_valid():
        for compat in compat_form.save(commit=False):
            compat.version = version
            compat.save()
        for form in compat_form.forms:
            if (isinstance(form, forms.CompatForm) and
                'max' in form.changed_data):
                _log_max_version_change(addon, version, form.instance)
    return jingo.render(request, 'devhub/addons/ajax_compat_update.html',
                        dict(addon=addon, version=version,
                             compat_form=compat_form))


def _get_addons(request, addons, addon_id, action):
    """Create a list of ``MenuItem``s for the activity feed."""
    items = []

    a = MenuItem()
    a.selected = (not addon_id)
    (a.text, a.url) = (_('All My Add-ons'), reverse('devhub.feed_all'))
    if action:
        a.url += '?action=' + action
    items.append(a)

    for addon in addons:
        item = MenuItem()
        try:
            item.selected = (addon_id and addon.id == int(addon_id))
        except ValueError:
            pass  # We won't get here... EVER
        url = reverse('devhub.feed', args=[addon.slug])
        if action:
            url += '?action=' + action
        item.text, item.url = addon.name, url
        items.append(item)

    return items


def _get_posts(limit=5):
    return BlogPost.objects.order_by('-date_posted')[0:limit]


def _get_activities(request, action):
    url = request.get_full_path()
    choices = (None, 'updates', 'status', 'collections', 'reviews')
    text = {None: _('All Activity'),
            'updates': _('Add-on Updates'),
            'status': _('Add-on Status'),
            'collections': _('User Collections'),
            'reviews': _('User Reviews'),
            }

    items = []
    for c in choices:
        i = MenuItem()
        i.text = text[c]
        i.url, i.selected = urlparams(url, page=None, action=c), (action == c)
        items.append(i)

    return items


def _get_items(action, addons):
    filters = dict(updates=(amo.LOG.ADD_VERSION, amo.LOG.ADD_FILE_TO_VERSION),
                   status=(amo.LOG.USER_DISABLE, amo.LOG.USER_ENABLE,
                           amo.LOG.CHANGE_STATUS, amo.LOG.APPROVE_VERSION,),
                   collections=(amo.LOG.ADD_TO_COLLECTION,
                            amo.LOG.REMOVE_FROM_COLLECTION,),
                   reviews=(amo.LOG.ADD_REVIEW,))

    filter = filters.get(action)
    items = (ActivityLog.objects.for_addons(addons).filter()
                        .exclude(action__in=amo.LOG_HIDE_DEVELOPER))
    if filter:
        items = items.filter(action__in=[i.id for i in filter])

    return items


def _get_rss_feed(request):
    key, __ = RssKey.objects.get_or_create(user=request.amo_user)
    return urlparams(reverse('devhub.feed_all'), privaterss=key.key)


def feed(request, addon_id=None):
    if request.GET.get('privaterss'):
        return feeds.ActivityFeedRSS()(request)

    addon_selected = None

    if not request.user.is_authenticated():
        url = reverse('users.login')
        p = urlquote(request.get_full_path())
        return http.HttpResponseRedirect('%s?to=%s' % (url, p))
    else:
        # We exclude apps on AMO.
        addons_all = request.amo_user.addons.exclude(type=amo.ADDON_WEBAPP)

        if addon_id:
            addon = get_object_or_404(Addon.objects.id_or_slug(addon_id))
            addons = addon  # common query set
            try:
                key = RssKey.objects.get(addon=addons)
            except RssKey.DoesNotExist:
                key = RssKey.objects.create(addon=addons)

            addon_selected = addon.id

            rssurl = urlparams(reverse('devhub.feed', args=[addon_id]),
                               privaterss=key.key)

            if not acl.check_addon_ownership(request, addons, viewer=True,
                                             ignore_disabled=True):
                return http.HttpResponseForbidden()
        else:
            rssurl = _get_rss_feed(request)
            addon = None
            addons = addons_all

    action = request.GET.get('action')

    items = _get_items(action, addons)

    activities = _get_activities(request, action)
    addon_items = _get_addons(request, addons_all, addon_selected, action)

    pager = amo.utils.paginate(request, items, 20)
    data = dict(addons=addon_items, pager=pager, activities=activities,
                rss=rssurl, addon=addon)
    return jingo.render(request, 'devhub/addons/activity.html', data)


@dev_required(webapp=True)
def edit(request, addon_id, addon, webapp=False):
    data = {
       'page': 'edit',
       'addon': addon,
       'webapp': webapp,
       'valid_slug': addon.slug,
       'tags': addon.tags.not_blacklisted().values_list('tag_text', flat=True),
       'previews': addon.previews.all(),
    }

    if webapp and waffle.switch_is_active('marketplace'):
        data['device_type_form'] = addon_forms.DeviceTypeForm(
            request.POST or None, addon=addon)

    if (not webapp and
        acl.action_allowed(request, 'Addons', 'Configure')):
        data['admin_form'] = forms.AdminForm(instance=addon)

    return jingo.render(request, 'devhub/addons/edit.html', data)


@dev_required(owner_for_post=True, webapp=True)
def delete(request, addon_id, addon, webapp=False):
    # Database deletes only allowed for free or incomplete addons.
    if not addon.can_be_deleted():
        if webapp:
            msg = loc('App cannot be deleted. Disable this app instead.')
        else:
            msg = _('Add-on cannot be deleted. Disable this add-on instead.')
        messages.error(request, msg)
        return redirect(addon.get_dev_url('versions'))

    form = forms.DeleteForm(request)
    if form.is_valid():
        addon.delete('Removed via devhub')
        messages.success(request,
            loc('App deleted.') if webapp else _('Add-on deleted.'))
        return redirect('devhub.%s' % ('apps' if webapp else 'addons'))
    else:
        if webapp:
            msg = loc('Password was incorrect. App was not deleted.')
        else:
            msg = _('Password was incorrect.  Add-on was not deleted.')
        messages.error(request, msg)
        return redirect(addon.get_dev_url('versions'))


@dev_required
def enable(request, addon_id, addon):
    addon.update(disabled_by_user=False)
    amo.log(amo.LOG.USER_ENABLE, addon)
    return redirect(addon.get_dev_url('versions'))


@dev_required(owner_for_post=True)
def cancel(request, addon_id, addon):
    if addon.status in amo.STATUS_UNDER_REVIEW:
        if addon.status == amo.STATUS_LITE_AND_NOMINATED:
            addon.update(status=amo.STATUS_LITE)
        else:
            addon.update(status=amo.STATUS_NULL)
        amo.log(amo.LOG.CHANGE_STATUS, addon.get_status_display(), addon)
    return redirect(addon.get_dev_url('versions'))


@dev_required
@post_required
def disable(request, addon_id, addon):
    addon.update(disabled_by_user=True)
    amo.log(amo.LOG.USER_DISABLE, addon)
    return redirect(addon.get_dev_url('versions'))


@dev_required(owner_for_post=True, webapp=True)
def ownership(request, addon_id, addon, webapp=False):
    fs, ctx = [], {}
    # Authors.
    qs = AddonUser.objects.filter(addon=addon).order_by('position')
    user_form = forms.AuthorFormSet(request.POST or None, queryset=qs)
    fs.append(user_form)
    # Versions.
    license_form = forms.LicenseForm(request.POST or None, addon=addon)
    if not addon.is_webapp():
        ctx.update(license_form.get_context())
        if ctx['license_form']:  # if addon has a version
            fs.append(ctx['license_form'])
    # Policy.
    policy_form = forms.PolicyForm(request.POST or None, addon=addon)
    if not addon.is_webapp():
        ctx.update(policy_form=policy_form)
        fs.append(policy_form)

    if request.method == 'POST' and all([form.is_valid() for form in fs]):
        # Authors.
        authors = user_form.save(commit=False)
        for author in authors:
            action = None
            if not author.id or author.user_id != author._original_user_id:
                action = amo.LOG.ADD_USER_WITH_ROLE
                author.addon = addon
            elif author.role != author._original_role:
                action = amo.LOG.CHANGE_USER_WITH_ROLE

            author.save()
            if action:
                amo.log(action, author.user, author.get_role_display(), addon)
            if (author._original_user_id and
                author.user_id != author._original_user_id):
                amo.log(amo.LOG.REMOVE_USER_WITH_ROLE,
                        (UserProfile, author._original_user_id),
                        author.get_role_display(), addon)

        for author in user_form.deleted_objects:
            amo.log(amo.LOG.REMOVE_USER_WITH_ROLE, author.user,
                    author.get_role_display(), addon)

        if license_form in fs:
            license_form.save()
        if policy_form in fs:
            policy_form.save()
        messages.success(request, _('Changes successfully saved.'))

        return redirect(addon.get_dev_url('owner'))

    ctx.update(addon=addon, webapp=webapp, user_form=user_form)
    return jingo.render(request, 'devhub/addons/owner.html', ctx)


@dev_required(owner_for_post=True, webapp=True)
def payments(request, addon_id, addon, webapp=False):
    if addon.is_premium():
        return _premium(request, addon_id, addon, webapp)
    return _voluntary(request, addon_id, addon, webapp)


def _premium(request, addon_id, addon, webapp=False):
    premium_form = forms.PremiumForm(request.POST or None,
                                     request=request,
                                     extra={'addon': addon,
                                            'amo_user': request.amo_user,
                                            'dest': 'payment'})
    if request.method == 'POST' and premium_form.is_valid():
        premium_form.save()
        messages.success(request, _('Changes successfully saved.'))
        return redirect(addon.get_dev_url('payments'))

    return jingo.render(request, 'devhub/payments/premium.html',
                        dict(addon=addon, webapp=webapp, premium=addon.premium,
                             form=premium_form))


def _voluntary(request, addon_id, addon, webapp):
    charity = None if addon.charity_id == amo.FOUNDATION_ORG else addon.charity
    charity_form = forms.CharityForm(request.POST or None, instance=charity,
                                     prefix='charity')
    contrib_form = forms.ContribForm(request.POST or None, instance=addon,
                                     initial=forms.ContribForm.initial(addon))
    profile_form = forms.ProfileForm(request.POST or None, instance=addon,
                                     required=True)
    if request.method == 'POST':
        if contrib_form.is_valid():
            addon = contrib_form.save(commit=False)
            addon.wants_contributions = True
            valid = _save_charity(addon, contrib_form, charity_form)
            if not addon.has_full_profile():
                valid &= profile_form.is_valid()
                if valid:
                    profile_form.save()
            if valid:
                addon.save()
                messages.success(request, _('Changes successfully saved.'))
                amo.log(amo.LOG.EDIT_CONTRIBUTIONS, addon)

                return redirect(addon.get_dev_url('payments'))
    errors = charity_form.errors or contrib_form.errors or profile_form.errors
    if errors:
        messages.error(request, _('There were errors in your submission.'))
    return jingo.render(request, 'devhub/payments/payments.html',
        dict(addon=addon, webapp=webapp, errors=errors,
             charity_form=charity_form, contrib_form=contrib_form,
             profile_form=profile_form))


def _save_charity(addon, contrib_form, charity_form):
    recipient = contrib_form.cleaned_data['recipient']
    if recipient == 'dev':
        addon.charity = None
    elif recipient == 'moz':
        addon.charity_id = amo.FOUNDATION_ORG
    elif recipient == 'org':
        if charity_form.is_valid():
            addon.charity = charity_form.save()
        else:
            return False
    return True


@write
@dev_required(webapp=True)
def acquire_refund_permission(request, addon_id, addon, webapp=False):
    """This is the callback from Paypal."""
    paypal_log.debug('User approved refund for addon: %s' % addon_id)
    token = paypal.get_permissions_token(request.GET['request_token'],
                                         request.GET['verification_code'])
    paypal_log.debug('Got refund token for addon: %s, token: %s....' %
                     (addon_id, token[:10]))

    # Sadly this is an update on a GET.
    addonpremium, created = (AddonPremium.objects
                                         .safer_get_or_create(addon=addon))

    paypal_log.debug('AddonPremium %s for: %s' %
                     ('created' if created else 'updated', addon.pk))
    addonpremium.update(paypal_permissions_token=token)

    paypal_log.debug('AddonPremium saved with token: %s' % addonpremium.pk)
    amo.log(amo.LOG.EDIT_PROPERTIES, addon)

    dest = 'payments'
    if request.GET.get('dest') == 'wizard':
        dest = 'market.1'
    return redirect(addon.get_dev_url(dest))

@waffle_switch('allow-refund')
@dev_required(webapp=True)
def issue_refund(request, addon_id, addon, webapp=False):
    txn_id = request.REQUEST.get('transaction_id')
    if not txn_id:
        raise http.Http404
    form_enabled = True
    contribution = get_object_or_404(Contribution, transaction_id=txn_id,
                                     type=amo.CONTRIB_PURCHASE)
    if Refund.objects.filter(contribution=contribution).exists():
        messages.error(request, _('Refund already processed.'))
        form_enabled = False

    elif request.method == 'POST':
        if 'issue' in request.POST:
            try:
                results = paypal.refund(contribution.paykey)
            except paypal.PaypalError, e:
                messages.error(request, _('Refund failed. error: %s') % e)
                contribution.record_failed_refund(e)
            else:
                for res in results:
                    if res['refundStatus'] == 'ALREADY_REVERSED_OR_REFUNDED':
                        paypal_log.debug(
                            'Refund attempt for already-refunded paykey: %s, %s'
                            % (contribution.paykey, res['receiver.email']))
                        messages.error(request,
                                       _('Refund was previously issued; '
                                         'no action taken.'))
                        return redirect(addon.get_dev_url('refunds'))
                contribution.mail_approved()
                refund = contribution.enqueue_refund(amo.REFUND_APPROVED)
                paypal_log.info('Refund %r issued for contribution %r' %
                                (refund.pk, contribution.pk))
                messages.success(request, _('Refund issued.'))
        else:
            contribution.mail_declined()
            # TODO: Consider requiring a rejection reason for declined refunds.
            refund = contribution.enqueue_refund(amo.REFUND_DECLINED)
            paypal_log.info('Refund %r declined for contribution %r' %
                            (refund.pk, contribution.pk))
            messages.success(request, _('Refund declined.'))
        return redirect(addon.get_dev_url('refunds'))

    return jingo.render(request, 'devhub/payments/issue-refund.html',
                        {'enabled': form_enabled,
                         'contribution': contribution,
                         'addon': addon,
                         'webapp': webapp,
                         'transaction_id': txn_id})


@waffle_switch('allow-refund')
@dev_required(webapp=True)
# TODO: Make sure 'Support' staff can access this.
def refunds(request, addon_id, addon, webapp=False):
    ctx = {'addon': addon, 'webapp': webapp}
    queues = {
        'pending': Refund.objects.pending(addon),
        'approved': Refund.objects.approved(addon),
        'instant': Refund.objects.instant(addon),
        'declined': Refund.objects.declined(addon),
    }
    # For now set the limit to something stupid so this is stupid easy to QA.
    for status, refunds in queues.iteritems():
        ctx[status] = amo.utils.paginate(request, refunds, per_page=5)
    return jingo.render(request, 'devhub/payments/refunds.html', ctx)


@dev_required
@post_required
def disable_payments(request, addon_id, addon):
    addon.update(wants_contributions=False)
    return redirect(addon.get_dev_url('payments'))


@dev_required(webapp=True)
@post_required
def remove_profile(request, addon_id, addon, webapp=False):
    delete_translation(addon, 'the_reason')
    delete_translation(addon, 'the_future')
    if addon.wants_contributions:
        addon.update(wants_contributions=False)
    return redirect(addon.get_dev_url('profile'))


@dev_required(webapp=True)
def profile(request, addon_id, addon, webapp=False):
    profile_form = forms.ProfileForm(request.POST or None, instance=addon)

    if request.method == 'POST' and profile_form.is_valid():
        profile_form.save()
        amo.log(amo.LOG.EDIT_PROPERTIES, addon)
        messages.success(request, _('Changes successfully saved.'))
        return redirect(addon.get_dev_url('profile'))

    return jingo.render(request, 'devhub/addons/profile.html',
                        dict(addon=addon, webapp=webapp,
                             profile_form=profile_form))


@login_required
@post_required
@json_view
def compat_application_versions(request):
    app_id = request.POST['application_id']
    f = CheckCompatibilityForm()
    return {'choices': f.version_choices_for_app_id(app_id)}


@login_required
def validate_addon(request):
    return jingo.render(request, 'devhub/validate_addon.html',
                        {'title': _('Validate Add-on'),
                         'upload_url': reverse('devhub.standalone_upload')})


@login_required
def check_addon_compatibility(request):
    form = CheckCompatibilityForm()
    return jingo.render(request, 'devhub/validate_addon.html',
                        {'appversion_form': form,
                         'title': _('Check Add-on Compatibility'),
                         'upload_url': reverse('devhub.standalone_upload')})


@dev_required
@json_view
def file_perf_tests_start(request, addon_id, addon, file_id):
    if not waffle.flag_is_active(request, 'perf-tests'):
        return http.HttpResponseForbidden()
    file_ = get_object_or_404(File, pk=file_id)

    plats = perf.PLATFORM_MAP.get(file_.platform.id, None)
    if plats is None:
        log.info('Unsupported performance platform %s for file %s'
                 % (file_.platform.id, file_))
        # TODO(Kumar) provide a message about this
        return {'success': False}

    for app in perf.ALL_APPS:
        for plat in plats:
            tasks.start_perf_test_for_file.delay(file_.id, plat, app)
    return {'success': True}


def packager_path(name):
    return os.path.join(settings.PACKAGER_PATH, '%s.zip' % name)


@anonymous_csrf
def package_addon(request):
    basic_form = forms.PackagerBasicForm(request.POST or None)
    features_form = forms.PackagerFeaturesForm(request.POST or None)
    compat_forms = forms.PackagerCompatFormSet(request.POST or None)

    # Process requests, but also avoid short circuiting by using all().
    if (request.method == 'POST' and
        all([basic_form.is_valid(),
             features_form.is_valid(),
             compat_forms.is_valid()])):

        basic_data = basic_form.cleaned_data
        compat_data = compat_forms.cleaned_data

        data = {'id': basic_data['id'],
                'version': basic_data['version'],
                'name': basic_data['name'],
                'slug': basic_data['package_name'],
                'description': basic_data['description'],
                'author_name': basic_data['author_name'],
                'contributors': basic_data['contributors'],
                'targetapplications': [c for c in compat_data if c['enabled']]}
        tasks.packager.delay(data, features_form.cleaned_data)
        return redirect('devhub.package_addon_success',
                        basic_data['package_name'])

    return jingo.render(request, 'devhub/package_addon.html',
                        {'basic_form': basic_form,
                         'compat_forms': compat_forms,
                         'features_form': features_form})


def package_addon_success(request, package_name):
    """Return the success page for the add-on packager."""
    return jingo.render(request, 'devhub/package_addon_success.html',
                        {'package_name': package_name})


@json_view
def package_addon_json(request, package_name):
    """Return the URL of the packaged add-on."""
    path_ = packager_path(package_name)
    if storage.exists(path_):
        url = reverse('devhub.package_addon_download', args=[package_name])
        return {'download_url': url, 'filename': os.path.basename(path_),
                'size': round(storage.open(path_).size / 1024, 1)}


def package_addon_download(request, package_name):
    """Serve a packaged add-on."""
    path_ = packager_path(package_name)
    if not storage.exists(path_):
        raise http.Http404()
    return HttpResponseSendFile(request, path_, content_type='application/zip')


@login_required
@post_required
def upload(request, addon_slug=None, is_standalone=False):
    filedata = request.FILES['upload']

    fu = FileUpload.from_post(filedata, filedata.name, filedata.size)
    log.info('FileUpload created: %s' % fu.pk)
    if request.user.is_authenticated():
        fu.user = request.amo_user
        fu.save()
    if request.POST.get('app_id') and request.POST.get('version_id'):
        app = get_object_or_404(Application, pk=request.POST['app_id'])
        ver = get_object_or_404(AppVersion, pk=request.POST['version_id'])
        tasks.compatibility_check.delay(fu.pk, app.guid, ver.version)
    else:
        tasks.validator.delay(fu.pk)
    if addon_slug:
        return redirect('devhub.upload_detail_for_addon',
                        addon_slug, fu.pk)
    elif is_standalone:
        return redirect('devhub.standalone_upload_detail', fu.pk)
    else:
        return redirect('devhub.upload_detail', fu.pk, 'json')


@login_required
@post_required
@json_view
def upload_manifest(request):
    form = forms.NewManifestForm(request.POST)
    if form.is_valid():
        upload = FileUpload.objects.create()
        tasks.fetch_manifest.delay(form.cleaned_data['manifest'], upload.pk)
        return redirect('devhub.upload_detail', upload.pk, 'json')
    else:
        error_text = _('There was an error with the submission.')
        if 'manifest' in form.errors:
            error_text = ' '.join(form.errors['manifest'])
        error_message = {'type': 'error', 'message': error_text, 'tier': 1}

        v = {'errors': 1, 'success': False, 'messages': [error_message]}
        return make_validation_result(dict(validation=v, error=error_text))


@login_required
@post_required
def standalone_upload(request):
    return upload(request, is_standalone=True)


@login_required
@json_view
def standalone_upload_detail(request, uuid):
    upload = get_object_or_404(FileUpload.uncached, uuid=uuid)
    url = reverse('devhub.standalone_upload_detail', args=[uuid])
    return upload_validation_context(request, upload, url=url)


@post_required
@dev_required
def upload_for_addon(request, addon_id, addon):
    return upload(request, addon_slug=addon.slug)


@dev_required
@json_view
def upload_detail_for_addon(request, addon_id, addon, uuid):
    upload = get_object_or_404(FileUpload.uncached, uuid=uuid)
    return json_upload_detail(request, upload, addon_slug=addon.slug)


def make_validation_result(data, is_compatibility=False):
    """Safe wrapper around JSON dict containing a validation result.

    Keyword Arguments

    **is_compatibility=False**
        When True, errors will be summarized as if they were in a regular
        validation result.
    """
    if not settings.EXPOSE_VALIDATOR_TRACEBACKS:
        if data['error']:
            # Just expose the message, not the traceback
            data['error'] = data['error'].strip().split('\n')[-1].strip()
    if data['validation']:
        lim = settings.VALIDATOR_MESSAGE_LIMIT
        if lim:
            del (data['validation']['messages']
                 [settings.VALIDATOR_MESSAGE_LIMIT:])
        ending_tier = data['validation'].get('ending_tier', 0)
        for msg in data['validation']['messages']:
            if msg['tier'] > ending_tier:
                ending_tier = msg['tier']
            if msg['tier'] == 0:
                # We can't display a message if it's on tier 0.
                # Should get fixed soon in bug 617481
                msg['tier'] = 1
            for k, v in msg.items():
                msg[k] = escape_all(v)
        if lim:
            compatibility_count = 0
            if data['validation'].get('compatibility_summary'):
                cs = data['validation']['compatibility_summary']
                compatibility_count = (cs['errors']
                                     + cs['warnings']
                                     + cs['notices'])
            else:
                cs = {}
            leftover_count = (data['validation'].get('errors', 0)
                            + data['validation'].get('warnings', 0)
                            + data['validation'].get('notices', 0)
                            + compatibility_count
                            - lim)
            if leftover_count > 0:
                if data['validation']['errors'] or cs.get('errors'):
                    msgtype = 'error'
                elif data['validation']['warnings'] or cs.get('warnings'):
                    msgtype = 'warning'
                else:
                    msgtype = 'notice'
                data['validation']['messages'].append(
                    {'tier': 1,
                     'type': msgtype,
                     'message': (_('Validation generated too many errors/'
                                   'warnings so %s messages were truncated. '
                                   'After addressing the visible messages, '
                                   "you'll be able to see the others.")
                                 % (leftover_count,)),
                     'compatibility_type': None
                     })
        if is_compatibility:
            compat = data['validation']['compatibility_summary']
            for k in ('errors', 'warnings', 'notices'):
                data['validation'][k] = compat[k]
            for msg in data['validation']['messages']:
                if msg['compatibility_type']:
                    msg['type'] = msg['compatibility_type']
        data['validation']['ending_tier'] = ending_tier
    return data


@dev_required(allow_editors=True)
def file_validation(request, addon_id, addon, file_id):
    file = get_object_or_404(File, id=file_id)

    v = reverse('devhub.json_file_validation', args=[addon.slug, file.id])
    return jingo.render(request, 'devhub/validation.html',
                        dict(validate_url=v, filename=file.filename,
                             timestamp=file.created,
                             addon=addon))


@dev_required(allow_editors=True)
def bulk_compat_result(request, addon_id, addon, result_id):
    qs = ValidationResult.objects.exclude(completed=None)
    result = get_object_or_404(qs, pk=result_id)
    job = result.validation_job
    revalidate_url = reverse('devhub.json_bulk_compat_result',
                             args=[addon.slug, result.id])
    return _compat_result(request, revalidate_url,
                          job.application, job.target_version,
                          for_addon=result.file.version.addon,
                          validated_filename=result.file.filename,
                          validated_ts=result.completed)


def _compat_result(request, revalidate_url, target_app, target_version,
                   validated_filename=None, validated_ts=None,
                   for_addon=None):
    app_trans = dict((g, unicode(a.pretty)) for g, a in amo.APP_GUIDS.items())
    ff_versions = (AppVersion.objects.filter(application=amo.FIREFOX.id,
                                             version_int__gte=4000000000000)
                   .values_list('application', 'version')
                   .order_by('version_int'))
    tpl = 'https://developer.mozilla.org/en/Firefox_%s_for_developers'
    change_links = dict()
    for app, ver in ff_versions:
        major = ver[0]  # 4.0b3 -> 4
        change_links['%s %s' % (amo.APP_IDS[app].guid, ver)] = tpl % major
    return jingo.render(request, 'devhub/validation.html',
                        dict(validate_url=revalidate_url,
                             filename=validated_filename,
                             timestamp=validated_ts,
                             target_app=target_app,
                             target_version=target_version,
                             addon=for_addon,
                             result_type='compat',
                             app_trans=app_trans,
                             version_change_links=change_links))


@json_view
@csrf_view_exempt
@dev_required(allow_editors=True)
def json_file_validation(request, addon_id, addon, file_id):
    file = get_object_or_404(File, id=file_id)
    if not file.has_been_validated == True:
        if request.method != 'POST':
            return http.HttpResponseNotAllowed(['POST'])

        try:
            v_result = tasks.file_validator(file.id)
        except Exception, exc:
            log.error('file_validator(%s): %s' % (file.id, exc))
            error = "\n".join(traceback.format_exception(*sys.exc_info()))
            return make_validation_result({'validation': '',
                                           'error': error})
    else:
        v_result = file.validation
    validation = json.loads(v_result.validation)

    return make_validation_result(dict(validation=validation,
                                       error=None))


@json_view
@csrf_view_exempt
@post_required
@dev_required(allow_editors=True)
def json_bulk_compat_result(request, addon_id, addon, result_id):
    qs = ValidationResult.objects.exclude(completed=None)
    result = get_object_or_404(qs, pk=result_id)
    if result.task_error:
        return make_validation_result({'validation': '',
                                       'error': result.task_error})
    else:
        validation = json.loads(result.validation)
        return make_validation_result(dict(validation=validation, error=None))


@json_view
def json_upload_detail(request, upload, addon_slug=None):
    addon = None
    if addon_slug:
        addon = get_object_or_404(Addon, slug=addon_slug)
    result = upload_validation_context(request, upload, addon=addon)
    plat_exclude = []
    if result['validation']:
        if result['validation']['errors'] == 0:
            try:
                pkg = parse_addon(upload, addon=addon)
                app_ids = set([a.id for a in pkg.get('apps', [])])
                supported_platforms = []
                for app in (amo.MOBILE, amo.ANDROID):
                    if app.id in app_ids:
                        supported_platforms.extend(amo.MOBILE_PLATFORMS.keys())
                        app_ids.remove(app.id)
                if len(app_ids):
                    # Targets any other non-mobile app:
                    supported_platforms.extend(amo.DESKTOP_PLATFORMS.keys())
                s = amo.SUPPORTED_PLATFORMS.keys()
                plat_exclude = set(s) - set(supported_platforms)
                plat_exclude = [str(p) for p in plat_exclude]
            except django_forms.ValidationError, exc:
                m = []
                for msg in exc.messages:
                    # Simulate a validation error so the UI displays
                    # it as such
                    m.append({'type': 'error',
                              'message': msg, 'tier': 1})
                v = make_validation_result(
                        dict(error='', validation=dict(messages=m)))
                return json_view.error(v)

    result['platforms_to_exclude'] = plat_exclude
    return result


def upload_validation_context(request, upload, addon_slug=None, addon=None,
                                       url=None):
    if addon_slug and not addon:
        addon = get_object_or_404(Addon, slug=addon_slug)
    if not settings.VALIDATE_ADDONS:
        upload.task_error = ''
        upload.validation = json.dumps({'errors': 0, 'messages': [],
                                        'metadata': {}, 'notices': 0,
                                        'warnings': 0})
        upload.save()

    validation = json.loads(upload.validation) if upload.validation else ""
    if not url:
        if addon:
            url = reverse('devhub.upload_detail_for_addon',
                          args=[addon.slug, upload.uuid])
        else:
            url = reverse('devhub.upload_detail', args=[upload.uuid, 'json'])
    full_report_url = reverse('devhub.upload_detail', args=[upload.uuid])

    return make_validation_result(dict(upload=upload.uuid,
                                       validation=validation,
                                       error=upload.task_error, url=url,
                                       full_report_url=full_report_url),
                                  is_compatibility=upload.compat_with_app)


@login_required
def upload_detail(request, uuid, format='html'):
    upload = get_object_or_404(FileUpload.uncached, uuid=uuid)

    if format == 'json' or request.is_ajax():
        return json_upload_detail(request, upload)

    validate_url = reverse('devhub.standalone_upload_detail',
                           args=[upload.uuid])
    if upload.compat_with_app:
        return _compat_result(request, validate_url,
                              upload.compat_with_app,
                              upload.compat_with_appver)
    return jingo.render(request, 'devhub/validation.html',
                        dict(validate_url=validate_url, filename=upload.name,
                             timestamp=upload.created))


class AddonDependencySearch(BaseAjaxSearch):
    # No personas. No webapps.
    types = [amo.ADDON_ANY, amo.ADDON_EXTENSION, amo.ADDON_THEME,
             amo.ADDON_DICT, amo.ADDON_SEARCH, amo.ADDON_LPAPP]


class AppDependencySearch(BaseAjaxSearch):
    # Only webapps.
    types = [amo.ADDON_WEBAPP]


@dev_required
@json_view
def ajax_dependencies(request, addon_id, addon):
    s = AppDependencySearch if addon.is_webapp() else AddonDependencySearch
    return s(request, excluded_ids=[addon_id]).items


@dev_required(webapp=True)
def addons_section(request, addon_id, addon, section, editable=False,
                   webapp=False):
    basic = addon_forms.AppFormBasic if webapp else addon_forms.AddonFormBasic
    models = {'basic': basic,
              'media': addon_forms.AddonFormMedia,
              'details': addon_forms.AddonFormDetails,
              'support': addon_forms.AddonFormSupport,
              'technical': addon_forms.AddonFormTechnical,
              'admin': forms.AdminForm}

    if section not in models:
        raise http.Http404()

    tags = previews = restricted_tags = []
    cat_form = dependency_form = device_type_form = None

    if section == 'basic':
        tags = addon.tags.not_blacklisted().values_list('tag_text', flat=True)
        cat_form = addon_forms.CategoryFormSet(request.POST or None,
                                               addon=addon, request=request)
        restricted_tags = addon.tags.filter(restricted=True)
        if webapp and waffle.switch_is_active('marketplace'):
            device_type_form = addon_forms.DeviceTypeForm(request.POST or None,
                                                          addon=addon)

    elif section == 'media':
        previews = forms.PreviewFormSet(request.POST or None,
            prefix='files', queryset=addon.previews.all())

    elif section == 'technical':
        if not webapp:
            dependency_form = forms.DependencyFormSet(request.POST or None,
                queryset=addon.addons_dependencies.all(), addon=addon,
                prefix='dependencies')

    # Get the slug before the form alters it to the form data.
    valid_slug = addon.slug
    if editable:
        if request.method == 'POST':
            form = models[section](request.POST, request.FILES,
                                   instance=addon, request=request)
            if form.is_valid() and (not previews or previews.is_valid()):
                addon = form.save(addon)

                if previews:
                    for preview in previews.forms:
                        preview.save(addon)

                editable = False
                if section == 'media':
                    amo.log(amo.LOG.CHANGE_ICON, addon)
                else:
                    amo.log(amo.LOG.EDIT_PROPERTIES, addon)

                valid_slug = addon.slug
            if cat_form:
                if cat_form.is_valid():
                    cat_form.save()
                    addon.save()
                else:
                    editable = True
            if device_type_form:
                if device_type_form.is_valid():
                    device_type_form.save(addon)
                    addon.save()
                else:
                    editable = True
            if dependency_form:
                if dependency_form.is_valid():
                    dependency_form.save()
                else:
                    editable = True
        else:
            form = models[section](instance=addon, request=request)
    else:
        form = False

    data = {'addon': addon,
            'webapp': webapp,
            'form': form,
            'editable': editable,
            'tags': tags,
            'restricted_tags': restricted_tags,
            'cat_form': cat_form,
            'preview_form': previews,
            'dependency_form': dependency_form,
            'valid_slug': valid_slug,
            'device_type_form': device_type_form}

    return jingo.render(request,
                        'devhub/addons/edit/%s.html' % section, data)


@never_cache
@dev_required
@json_view
def image_status(request, addon_id, addon):
    # Default icon needs no checking.
    if not addon.icon_type or addon.icon_type.split('/')[0] == 'icon':
        icons = True
    # Persona icon is handled differently.
    elif addon.type == amo.ADDON_PERSONA:
        icons = True
    else:
        icons = storage.exists(os.path.join(addon.get_icon_dir(),
                                            '%s-32.png' % addon.id))
    previews = all(storage.exists(p.thumbnail_path)
                   for p in addon.previews.all())
    return {'overall': icons and previews,
            'icons': icons,
            'previews': previews}


@json_view
def ajax_upload_image(request, upload_type):
    errors = []
    upload_hash = ''

    if 'upload_image' in request.FILES:
        upload_preview = request.FILES['upload_image']
        upload_preview.seek(0)

        upload_hash = uuid.uuid4().hex
        loc = os.path.join(settings.TMP_PATH, upload_type, upload_hash)

        with storage.open(loc, 'wb') as fd:
            for chunk in upload_preview:
                fd.write(chunk)

        is_icon = upload_type == 'icon'
        is_persona = upload_type.startswith('persona_')

        check = amo.utils.ImageCheck(upload_preview)
        if (not check.is_image() or
            upload_preview.content_type not in amo.IMG_TYPES):
            if is_icon:
                errors.append(_('Icons must be either PNG or JPG.'))
            else:
                errors.append(_('Images must be either PNG or JPG.'))

        if check.is_animated():
            if is_icon:
                errors.append(_('Icons cannot be animated.'))
            else:
                errors.append(_('Images cannot be animated.'))

        max_size = None
        if is_icon:
            max_size = settings.MAX_ICON_UPLOAD_SIZE
        if is_persona:
            max_size = settings.MAX_PERSONA_UPLOAD_SIZE

        if max_size and upload_preview.size > max_size:
            if is_icon:
                errors.append(_('Please use images smaller than %dMB.') % (
                    max_size / 1024 / 1024 - 1))
            if is_persona:
                errors.append(_('Images cannot be larger than %dKB.') % (
                    max_size / 1024))

        if check.is_image() and is_persona:
            persona, img_type = upload_type.split('_')  # 'header' or 'footer'
            expected_size = amo.PERSONA_IMAGE_SIZES.get(img_type)[1]
            with storage.open(loc, 'rb') as fp:
                actual_size = Image.open(fp).size
            if actual_size != expected_size:
                # L10n: {0} is an image width (in pixels), {1} is a height.
                errors.append(_('Image must be exactly {0} pixels wide '
                                'and {1} pixels tall.')
                              .format(expected_size[0], expected_size[1]))
    else:
        errors.append(_('There was an error uploading your preview.'))

    if errors:
        upload_hash = ''

    return {'upload_hash': upload_hash, 'errors': errors}


@dev_required
def upload_image(request, addon_id, addon, upload_type):
    return ajax_upload_image(request, upload_type)


@dev_required
def version_edit(request, addon_id, addon, version_id):
    version = get_object_or_404(Version, pk=version_id, addon=addon)
    version_form = forms.VersionForm(request.POST or None, instance=version)

    new_file_form = forms.NewFileForm(request.POST or None,
                                      addon=addon, version=version)

    file_form = forms.FileFormSet(request.POST or None, prefix='files',
                                  queryset=version.files.all())
    file_history = _get_file_history(version)

    data = {'version_form': version_form, 'file_form': file_form}

    if addon.accepts_compatible_apps():
        # We should be in no-caching land but this one stays cached for some
        # reason.
        qs = version.apps.all().no_cache()
        compat_form = forms.CompatFormSet(request.POST or None, queryset=qs)
        data['compat_form'] = compat_form

    if (request.method == 'POST' and
        all([form.is_valid() for form in data.values()])):
        data['version_form'].save()
        data['file_form'].save()

        for deleted in data['file_form'].deleted_forms:
            file = deleted.cleaned_data['id']
            amo.log(amo.LOG.DELETE_FILE_FROM_VERSION,
                    file.filename, file.version, addon)

        if 'compat_form' in data:
            for compat in data['compat_form'].save(commit=False):
                compat.version = version
                compat.save()
            for form in data['compat_form'].forms:
                if (isinstance(form, forms.CompatForm) and
                    'max' in form.changed_data):
                    _log_max_version_change(addon, version, form.instance)
        messages.success(request, _('Changes successfully saved.'))
        return redirect('devhub.versions.edit', addon.slug, version_id)

    data.update(addon=addon, version=version, new_file_form=new_file_form,
                file_history=file_history)
    return jingo.render(request, 'devhub/versions/edit.html', data)


def _log_max_version_change(addon, version, appversion):
    details = {'version': version.version,
               'target': appversion.version.version,
               'application': appversion.application.pk}
    amo.log(amo.LOG.MAX_APPVERSION_UPDATED,
            addon, version, details=details)


def _get_file_history(version):
    file_ids = [f.id for f in version.all_files]
    addon = version.addon
    file_history = (ActivityLog.objects.for_addons(addon)
                               .filter(action__in=amo.LOG_REVIEW_QUEUE))
    files = dict([(fid, []) for fid in file_ids])
    for log in file_history:
        details = log.details
        current_file_ids = details["files"] if 'files' in details else []
        for fid in current_file_ids:
            if fid in file_ids:
                files[fid].append(log)

    return files


@dev_required
@post_required
@transaction.commit_on_success
def version_delete(request, addon_id, addon):
    version_id = request.POST.get('version_id')
    version = get_object_or_404(Version, pk=version_id, addon=addon)
    messages.success(request, _('Version %s deleted.') % version.version)
    version.delete()
    return redirect(addon.get_dev_url('versions'))


@json_view
@dev_required
@post_required
def version_add(request, addon_id, addon):
    form = forms.NewVersionForm(request.POST, addon=addon)
    if form.is_valid():
        pl = (list(form.cleaned_data['desktop_platforms']) +
              list(form.cleaned_data['mobile_platforms']))
        v = Version.from_upload(form.cleaned_data['upload'], addon, pl)
        log.info('Version created: %s for: %s' %
                 (v.pk, form.cleaned_data['upload']))
        url = reverse('devhub.versions.edit', args=[addon.slug, str(v.id)])
        return dict(url=url)
    else:
        return json_view.error(form.errors)


@json_view
@dev_required
@post_required
def version_add_file(request, addon_id, addon, version_id):
    version = get_object_or_404(Version, pk=version_id, addon=addon)
    form = forms.NewFileForm(request.POST, addon=addon, version=version)
    if not form.is_valid():
        return json_view.error(form.errors)
    upload = form.cleaned_data['upload']
    new_file = File.from_upload(upload, version, form.cleaned_data['platform'],
                                parse_addon(upload, addon))
    storage.delete(upload.path)
    file_form = forms.FileFormSet(prefix='files', queryset=version.files.all())
    form = [f for f in file_form.forms if f.instance == new_file]
    return jingo.render(request, 'devhub/includes/version_file.html',
                        {'form': form[0], 'addon': addon})


@dev_required(webapp=True)
def version_list(request, addon_id, addon, webapp=False):
    qs = addon.versions.order_by('-created').transform(Version.transformer)
    versions = amo.utils.paginate(request, qs)
    new_file_form = forms.NewVersionForm(None, addon=addon)

    data = {'addon': addon,
            'webapp': webapp,
            'versions': versions,
            'new_file_form': new_file_form,
            'position': get_position(addon),
            'timestamp': int(time.time())}
    return jingo.render(request, 'devhub/versions/list.html', data)


@dev_required
def version_bounce(request, addon_id, addon, version):
    # Use filter since there could be dupes.
    vs = (Version.objects.filter(version=version, addon=addon)
          .order_by('-created'))
    if vs:
        return redirect('devhub.versions.edit', addon.slug, vs[0].id)
    else:
        raise http.Http404()


@json_view
@dev_required
def version_stats(request, addon_id, addon):
    qs = Version.objects.filter(addon=addon)
    reviews = (qs.annotate(reviews=Count('reviews'))
               .values('id', 'version', 'reviews'))
    d = dict((v['id'], v) for v in reviews)
    files = qs.annotate(files=Count('files')).values_list('id', 'files')
    for id, files in files:
        d[id]['files'] = files
    return d


Step = collections.namedtuple('Step', 'current max')


def submit_step(outer_step):
    """Wraps the function with a decorator that bounces to the right step."""
    def decorator(f):
        @functools.wraps(f)
        def wrapper(request, *args, **kw):
            step = outer_step
            webapp = kw.get('webapp', False)
            if webapp and step == 7:
                # decorator calls this step 7, but it's step 5 for apps
                step = 5
            max_step = 5 if webapp else 7
            # We only bounce on pages with an addon id.
            if 'addon' in kw:
                addon = kw['addon']
                on_step = SubmitStep.objects.filter(addon=addon)
                if on_step:
                    max_step = on_step[0].step
                    if max_step < step:
                        # The step was too high, so bounce to the saved step.
                        return redirect(_step_url(max_step, webapp),
                                        addon.slug)
                elif step != max_step:
                    # We couldn't find a step, so we must be done.
                    return redirect(_step_url(7, webapp), addon.slug)
            kw['step'] = Step(step, max_step)
            return f(request, *args, **kw)
        # Tell @dev_required that this is a function in the submit flow so it
        # doesn't try to redirect into the submit flow.
        wrapper.submitting = True
        return wrapper
    return decorator


@dev_required(webapp=True)
@can_become_premium
def marketplace_paypal(request, addon_id, addon, webapp=False):
    """
    Start of the marketplace wizard, none of this means anything until
    addon-premium is set, so we'll just save as we go along. Further
    we might have the PayPal permissions bounce happen at any time
    so we'll need to cope with AddonPremium being incomplete.
    """
    form = forms.PremiumForm(request.POST or None,
                             request=request,
                             extra={'addon': addon,
                                    'amo_user': request.amo_user,
                                    'dest': 'wizard',
                                    'exclude': ['price']})
    if form.is_valid():
        form.save()
        return redirect(addon.get_dev_url('market.2'))

    return jingo.render(request, 'devhub/payments/paypal.html',
                        {'form': form, 'addon': addon, 'webapp': webapp,
                         'premium': addon.premium})


@dev_required(webapp=True)
@can_become_premium
def marketplace_pricing(request, addon_id, addon, webapp=False):
    form = forms.PremiumForm(request.POST or None,
                             request=request,
                             extra={'addon': addon,
                                    'amo_user': request.amo_user,
                                    'dest': 'wizard',
                                    'exclude': ['paypal_id',
                                                'support_email']})
    if form.is_valid():
        form.save()
        if not (form.fields['free'].queryset.count()):
            return redirect(addon.get_dev_url('market.4'))
        return redirect(addon.get_dev_url('market.3'))
    return jingo.render(request, 'devhub/payments/tier.html',
                        {'form': form, 'addon': addon, 'webapp': webapp,
                         'premium': addon.premium})


@dev_required(webapp=True)
@can_become_premium
def marketplace_upsell(request, addon_id, addon, webapp=False):
    form = forms.PremiumForm(request.POST or None,
                             request=request,
                             extra={'addon': addon,
                                    'amo_user': request.amo_user,
                                    'dest': 'wizard',
                                    'exclude': ['price', 'paypal_id',
                                                'support_email']})
    if form.is_valid():
        form.save()
        return redirect(addon.get_dev_url('market.4'))
    return jingo.render(request, 'devhub/payments/upsell.html',
                        {'form': form, 'addon': addon, 'webapp': webapp,
                         'premium': addon.premium})


@dev_required(webapp=True)
@can_become_premium
def marketplace_confirm(request, addon_id, addon, webapp=False):
    if request.method == 'POST':
        if (addon.premium and addon.premium.is_complete()
            and addon.premium.has_permissions_token()):
            if addon.status == amo.STATUS_UNREVIEWED:
                addon.status = amo.STATUS_NOMINATED
            addon.premium_type = amo.ADDON_PREMIUM
            addon.save()
            amo.log(amo.LOG.MAKE_PREMIUM, addon)
            return redirect(addon.get_dev_url('payments'))

        messages.error(request, 'Some required details are missing.')
        return redirect(addon.get_dev_url('market.1'))

    return jingo.render(request, 'devhub/payments/second-confirm.html',
                        {'addon': addon, 'webapp': webapp,
                         'upsell': addon.upsold, 'premium': addon.premium})


def _step_url(step, is_webapp):
    url_base = 'devhub.submit%s' % ('_apps' if is_webapp else '')
    if is_webapp and str(step).isdigit() and step > 5:
        step = 5
    return '%s.%s' % (url_base, step)


@login_required
@submit_step(1)
def submit(request, step, webapp=False):
    if request.method == 'POST':
        response = redirect(_step_url(2, webapp))
        response.set_cookie(DEV_AGREEMENT_COOKIE)
        return response

    return jingo.render(request, 'devhub/addons/submit/start.html',
                        {'step': step, 'webapp': webapp})


@login_required
@submit_step(2)
def submit_addon(request, step, webapp=False):
    if DEV_AGREEMENT_COOKIE not in request.COOKIES:
        return redirect(_step_url(1, webapp))
    NewItem = forms.NewWebappForm if webapp else forms.NewAddonForm
    form = NewItem(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            data = form.cleaned_data

            if webapp:
                p = [Platform.objects.get(id=amo.PLATFORM_ALL.id)]
            else:
                p = (list(data.get('desktop_platforms', [])) +
                     list(data.get('mobile_platforms', [])))

            addon = Addon.from_upload(data['upload'], p)
            if webapp:
                tasks.fetch_icon.delay(addon)
            AddonUser(addon=addon, user=request.amo_user).save()
            SubmitStep.objects.create(addon=addon, step=3)
            return redirect(_step_url(3, webapp), addon.slug)
    template = 'upload_webapp.html' if webapp else 'upload.html'
    return jingo.render(request, 'devhub/addons/submit/%s' % template,
            {'step': step, 'webapp': webapp, 'new_addon_form': form})


@dev_required(webapp=True)
@submit_step(3)
def submit_describe(request, addon_id, addon, step, webapp=False):
    form_cls = forms.Step3WebappForm if addon.is_webapp() else forms.Step3Form
    form = form_cls(request.POST or None, instance=addon, request=request)
    cat_form = addon_forms.CategoryFormSet(request.POST or None, addon=addon,
                                           request=request)
    device_form = None
    if webapp and waffle.switch_is_active('marketplace'):
        device_form = addon_forms.DeviceTypeForm(request.POST or None,
                                                 addon=addon)

    if request.method == 'POST' and form.is_valid() and cat_form.is_valid():
        if not device_form or device_form.is_valid():
            addon = form.save(addon)
            cat_form.save()
            if device_form:
                device_form.save(addon)
            SubmitStep.objects.filter(addon=addon).update(step=4)
            return redirect(_step_url(4, webapp), addon.slug)
    return jingo.render(request, 'devhub/addons/submit/describe.html',
                        {'form': form, 'cat_form': cat_form, 'addon': addon,
                         'step': step, 'webapp': addon.is_webapp(),
                         'device_form': device_form})


@dev_required(webapp=True)
@submit_step(4)
def submit_media(request, addon_id, addon, step, webapp=False):
    form_icon = addon_forms.AddonFormMedia(request.POST or None,
            request.FILES or None, instance=addon, request=request)
    form_previews = forms.PreviewFormSet(request.POST or None,
            prefix='files', queryset=addon.previews.all())

    if (request.method == 'POST' and
        form_icon.is_valid() and form_previews.is_valid()):
        addon = form_icon.save(addon)

        for preview in form_previews.forms:
            preview.save(addon)

        SubmitStep.objects.filter(addon=addon).update(step=5)

        # Special handling for webapps, where this is jumping to the done step
        if addon.is_webapp():
            addon.update(status=amo.WEBAPPS_UNREVIEWED_STATUS)
            SubmitStep.objects.filter(addon=addon).delete()
            signals.submission_done.send(sender=addon)

        return redirect(_step_url(5, webapp), addon.slug)

    return jingo.render(request, 'devhub/addons/submit/media.html',
                        {'form': form_icon, 'addon': addon, 'step': step,
                         'preview_form': form_previews,
                         'webapp': addon.is_webapp()})


@dev_required(webapp=True)
@submit_step(5)
def submit_license(request, addon_id, addon, step, webapp=False):
    fs, ctx = [], {}
    # Versions.
    license_form = forms.LicenseForm(request.POST or None, addon=addon)
    if not addon.is_webapp():
        ctx.update(license_form.get_context())
        fs.append(ctx['license_form'])
    # Policy.
    policy_form = forms.PolicyForm(request.POST or None, addon=addon)
    fs.append(policy_form)
    if request.method == 'POST' and all([form.is_valid() for form in fs]):
        if license_form in fs:
            license_form.save(log=False)
        policy_form.save()
        SubmitStep.objects.filter(addon=addon).update(step=6)
        return redirect('devhub.submit.6', addon.slug)
    ctx.update(addon=addon, policy_form=policy_form, step=step,
               webapp=addon.is_webapp())
    return jingo.render(request, 'devhub/addons/submit/license.html', ctx)


@dev_required
@submit_step(6)
def submit_select_review(request, addon_id, addon, step):
    review_type_form = forms.ReviewTypeForm(request.POST or None)
    updated_status = None

    if request.method == 'POST' and review_type_form.is_valid():
        updated_status = review_type_form.cleaned_data['review_type']

    if updated_status:
        addon.update(status=updated_status)
        SubmitStep.objects.filter(addon=addon).delete()
        signals.submission_done.send(sender=addon)
        return redirect('devhub.submit.7', addon.slug)

    return jingo.render(request, 'devhub/addons/submit/select-review.html',
                        {'addon': addon, 'review_type_form': review_type_form,
                         'step': step})


@dev_required(webapp=True)
@submit_step(7)
def submit_done(request, addon_id, addon, step, webapp=False):
    # Bounce to the versions page if they don't have any versions.
    if not addon.versions.exists():
        return redirect(addon.get_dev_url('versions'))
    sp = addon.current_version.supported_platforms
    is_platform_specific = sp != [amo.PLATFORM_ALL]

    return jingo.render(request, 'devhub/addons/submit/done.html',
                        {'addon': addon, 'step': step,
                         'webapp': addon.is_webapp(),
                         'is_platform_specific': is_platform_specific})


@dev_required
def submit_resume(request, addon_id, addon):
    step = SubmitStep.objects.filter(addon=addon)
    return _resume(addon, step)


def _resume(addon, step):
    if step:
        return redirect(_step_url(step[0].step, addon.is_webapp()), addon.slug)

    return redirect(addon.get_dev_url('versions'))


@login_required
@dev_required
def submit_bump(request, addon_id, addon, webapp=False):
    if not acl.action_allowed(request, 'Admin', 'EditSubmitStep'):
        return http.HttpResponseForbidden()
    step = SubmitStep.objects.filter(addon=addon)
    step = step[0] if step else None
    if request.method == 'POST' and request.POST.get('step'):
        new_step = request.POST['step']
        if step:
            step.step = new_step
        else:
            step = SubmitStep(addon=addon, step=new_step)
        step.save()
        return redirect(_step_url('bump', webapp), addon.slug)
    return jingo.render(request, 'devhub/addons/submit/bump.html',
                        dict(addon=addon, step=step))


@login_required
def submit_persona(request):
    if not waffle.flag_is_active(request, 'submit-personas'):
        return http.HttpResponseForbidden()
    form = addon_forms.NewPersonaForm(data=request.POST or None,
                                      files=request.FILES or None,
                                      request=request)
    if request.method == 'POST' and form.is_valid():
        addon = form.save()
        return redirect('devhub.personas.submit.done', addon.slug)
    return jingo.render(request, 'devhub/personas/submit.html',
                        dict(form=form))


@dev_required
def submit_persona_done(request, addon_id, addon):
    if not waffle.flag_is_active(request, 'submit-personas'):
        return http.HttpResponseForbidden()
    if addon.is_public():
        return redirect(addon.get_url_path())
    return jingo.render(request, 'devhub/personas/submit_done.html',
                        dict(addon=addon))


@dev_required
@post_required
def remove_locale(request, addon_id, addon):
    POST = request.POST
    if 'locale' in POST and POST['locale'] != addon.default_locale:
        addon.remove_locale(POST['locale'])
        return http.HttpResponse()
    return http.HttpResponseBadRequest()


# You can only request one of the new review tracks.
REQUEST_REVIEW = (amo.STATUS_PUBLIC, amo.STATUS_LITE)


@dev_required
@post_required
def request_review(request, addon_id, addon, status):
    status_req = int(status)
    if status_req not in addon.can_request_review():
        return http.HttpResponseBadRequest()
    elif status_req == amo.STATUS_PUBLIC:
        if addon.status == amo.STATUS_LITE:
            new_status = amo.STATUS_LITE_AND_NOMINATED
        else:
            new_status = amo.STATUS_NOMINATED
    elif status_req == amo.STATUS_LITE:
        if addon.status in (amo.STATUS_PUBLIC, amo.STATUS_LITE_AND_NOMINATED):
            new_status = amo.STATUS_LITE
        else:
            new_status = amo.STATUS_UNREVIEWED

    addon.update(status=new_status)
    msg = {amo.STATUS_LITE: _('Preliminary Review Requested.'),
           amo.STATUS_PUBLIC: _('Full Review Requested.')}
    messages.success(request, msg[status_req])
    amo.log(amo.LOG.CHANGE_STATUS, addon.get_status_display(), addon)
    return redirect(addon.get_dev_url('versions'))


# TODO(kumar): Remove when the editor tools are in zamboni.
def validator_redirect(request, version_id):
    v = get_object_or_404(Version, id=version_id)
    return redirect('devhub.addons.versions', v.addon_id, permanent=True)


@post_required
@addon_view
def admin(request, addon):
    if not acl.action_allowed(request, 'Addons', 'Configure'):
        return http.HttpResponseForbidden()
    form = forms.AdminForm(request, request.POST or None, instance=addon)
    if form.is_valid():
        form.save()
    return jingo.render(request, 'devhub/addons/edit/admin.html',
                        {'addon': addon, 'admin_form': form})


def docs(request, doc_name=None, doc_page=None):
    filename = ''

    all_docs = {'getting-started': [], 'reference': [],
                'policies': ['submission', 'reviews', 'maintenance',
                             'recommended', 'agreement', 'contact'],
                'case-studies': ['cooliris', 'stumbleupon',
                                 'download-statusbar'],
                'how-to': ['getting-started', 'extension-development',
                           'thunderbird-mobile', 'theme-development',
                           'other-addons']}

    if waffle.switch_is_active('marketplace'):
        all_docs['marketplace'] = ['voluntary']

    if doc_name and doc_name in all_docs:
        filename = '%s.html' % doc_name
        if doc_page and doc_page in all_docs[doc_name]:
            filename = '%s-%s.html' % (doc_name, doc_page)

    if not filename:
        return redirect('devhub.index')

    return jingo.render(request, 'devhub/docs/%s' % filename)


def builder(request):
    return jingo.render(request, 'devhub/builder.html')


@json_view
@post_required
def check_paypal(request):
    if 'email' not in request.POST:
        raise http.Http404()

    check = Check(paypal_id=request.POST['email'])
    check.all()
    # TODO(andym): we will want to l10n these messages at some point and
    # we'll need to change this to give more detail back to the user than
    # a tooltip at a later date.
    return {'valid': check.passed, 'message': ' '.join(check.errors)}


def search(request):
    query = request.GET.get('q', '')
    return jingo.render(request, 'devhub/devhub_search.html', {'query': query})
