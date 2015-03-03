import collections
import functools
import json
import os
import sys
import time
import traceback
import uuid

from django import forms as django_forms
from django import http
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage as storage
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.template import Context, loader
from django.utils.http import urlquote
from django.utils.timezone import now
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

import commonware.log
import waffle
from PIL import Image
from tower import ugettext as _
from tower import ugettext_lazy as _lazy

import amo
import amo.utils
from access import acl
from addons import forms as addon_forms
from addons.decorators import addon_view
from addons.models import Addon, AddonUser
from addons.views import BaseFilter
from amo import messages
from amo.decorators import json_view, login_required, post_required, write
from amo.helpers import absolutify, urlparams
from amo.urlresolvers import reverse
from amo.utils import escape_all, MenuItem
from applications.models import AppVersion
from devhub import perf
from devhub.decorators import dev_required
from devhub.forms import CheckCompatibilityForm
from devhub.models import ActivityLog, BlogPost, RssKey, SubmitStep
from devhub.utils import hide_traceback, make_validation_results
from editors.helpers import get_position, ReviewHelper
from files.models import File, FileUpload
from files.utils import is_beta, parse_addon
from search.views import BaseAjaxSearch
from translations.models import delete_translation
from users.models import UserProfile
from versions.compare import version_int
from versions.models import Version
from zadmin.models import ValidationResult

from . import forms, tasks, feeds, signals


log = commonware.log.getLogger('z.devhub')
paypal_log = commonware.log.getLogger('z.paypal')


# We use a session cookie to make sure people see the dev agreement.
DEV_AGREEMENT_COOKIE = 'yes-I-read-the-dev-agreement'

MDN_BASE = 'https://developer.mozilla.org/Add-ons'


class AddonFilter(BaseFilter):
    opts = (('name', _lazy(u'Name')),
            ('updated', _lazy(u'Updated')),
            ('created', _lazy(u'Created')),
            ('popular', _lazy(u'Downloads')),
            ('rating', _lazy(u'Rating')))


class ThemeFilter(BaseFilter):
    opts = (('name', _lazy(u'Name')),
            ('created', _lazy(u'Created')),
            ('popular', _lazy(u'Downloads')),
            ('rating', _lazy(u'Rating')))


def addon_listing(request, default='name', theme=False):
    """Set up the queryset and filtering for addon listing for Dashboard."""
    if theme:
        qs = request.amo_user.addons.filter(type=amo.ADDON_PERSONA)
        model = Addon
    else:
        qs = request.amo_user.addons.exclude(type=amo.ADDON_PERSONA)
        model = Addon
    filter_cls = ThemeFilter if theme else AddonFilter
    filter = filter_cls(request, qs, 'sort', default, model=model)
    return filter.qs, filter


def index(request):

    ctx = {'blog_posts': _get_posts()}
    if request.amo_user:
        user_addons = request.amo_user.addons.all()
        recent_addons = user_addons.order_by('-modified')[:3]
        ctx['recent_addons'] = []
        for addon in recent_addons:
            ctx['recent_addons'].append({'addon': addon,
                                         'position': get_position(addon)})

    return render(request, 'devhub/index.html', ctx)


@login_required
def dashboard(request, theme=False):
    addon_items = _get_items(
        None, request.amo_user.addons.all())[:4]

    data = dict(rss=_get_rss_feed(request), blog_posts=_get_posts(),
                timestamp=int(time.time()), addon_tab=not theme,
                theme=theme, addon_items=addon_items)

    if data['addon_tab']:
        addons, data['filter'] = addon_listing(request)
        data['addons'] = amo.utils.paginate(request, addons, per_page=10)

    if theme:
        themes, data['filter'] = addon_listing(request, theme=True)
        data['themes'] = amo.utils.paginate(request, themes, per_page=10)

    if 'filter' in data:
        data['sorting'] = data['filter'].field
        data['sort_opts'] = data['filter'].opts

    return render(request, 'devhub/addons/dashboard.html', data)


@dev_required
def ajax_compat_status(request, addon_id, addon):
    if not (addon.accepts_compatible_apps() and addon.current_version):
        raise http.Http404()
    return render(request, 'devhub/addons/ajax_compat_status.html',
                  dict(addon=addon))


@dev_required
def ajax_compat_error(request, addon_id, addon):
    if not (addon.accepts_compatible_apps() and addon.current_version):
        raise http.Http404()
    return render(request, 'devhub/addons/ajax_compat_error.html',
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
    return render(request, 'devhub/addons/ajax_compat_update.html',
                  dict(addon=addon, version=version, compat_form=compat_form))


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
        addons_all = request.amo_user.addons.all()

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
                raise PermissionDenied
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
    return render(request, 'devhub/addons/activity.html', data)


@dev_required
def edit(request, addon_id, addon):
    url_prefix = 'addons'

    data = {
        'page': 'edit',
        'addon': addon,
        'url_prefix': url_prefix,
        'valid_slug': addon.slug,
        'tags': addon.tags.not_blacklisted().values_list('tag_text',
                                                         flat=True),
        'previews': addon.previews.all(),
    }

    if acl.action_allowed(request, 'Addons', 'Configure'):
        data['admin_form'] = forms.AdminForm(instance=addon)

    return render(request, 'devhub/addons/edit.html', data)


@dev_required(theme=True)
def edit_theme(request, addon_id, addon, theme=False):
    form = addon_forms.EditThemeForm(data=request.POST or None,
                                     request=request, instance=addon)
    owner_form = addon_forms.EditThemeOwnerForm(data=request.POST or None,
                                                instance=addon)

    if request.method == 'POST':
        if 'owner_submit' in request.POST:
            if owner_form.is_valid():
                owner_form.save()
                messages.success(request, _('Changes successfully saved.'))
                return redirect('devhub.themes.edit', addon.slug)
        elif form.is_valid():
            form.save()
            messages.success(request, _('Changes successfully saved.'))
            return redirect('devhub.themes.edit', addon.reload().slug)
        else:
            messages.error(request, _('Please check the form for errors.'))

    return render(request, 'devhub/personas/edit.html', {
        'addon': addon, 'persona': addon.persona, 'form': form,
        'owner_form': owner_form})


@dev_required(owner_for_post=True, theme=True)
@post_required
def delete(request, addon_id, addon, theme=False):
    # Database deletes only allowed for free or incomplete addons.
    if not addon.can_be_deleted():
        msg = _('Add-on cannot be deleted. Disable this add-on instead.')
        messages.error(request, msg)
        return redirect(addon.get_dev_url('versions'))

    form = forms.DeleteForm(request)
    if form.is_valid():
        reason = form.cleaned_data.get('reason', '')
        addon.delete(msg='Removed via devhub', reason=reason)
        messages.success(
            request,
            _('Theme deleted.') if theme else _('Add-on deleted.'))
        return redirect('devhub.%s' % ('themes' if theme else 'addons'))
    else:
        if theme:
            messages.error(
                request,
                _('Password was incorrect. Theme was not deleted.'))
            return redirect(addon.get_dev_url())
        else:
            messages.error(
                request,
                _('Password was incorrect. Add-on was not deleted.'))
            return redirect(addon.get_dev_url('versions'))


@dev_required
@post_required
def enable(request, addon_id, addon):
    addon.update(disabled_by_user=False)
    amo.log(amo.LOG.USER_ENABLE, addon)
    return redirect(addon.get_dev_url('versions'))


@dev_required(owner_for_post=True)
@post_required
def cancel(request, addon_id, addon):
    if addon.status in amo.UNDER_REVIEW_STATUSES:
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


@dev_required(owner_for_post=True)
def ownership(request, addon_id, addon):
    fs, ctx = [], {}
    # Authors.
    qs = AddonUser.objects.filter(addon=addon).order_by('position')
    user_form = forms.AuthorFormSet(request.POST or None, queryset=qs)
    fs.append(user_form)
    # Versions.
    license_form = forms.LicenseForm(request.POST or None, addon=addon)
    ctx.update(license_form.get_context())
    if ctx['license_form']:  # if addon has a version
        fs.append(ctx['license_form'])
    # Policy.
    policy_form = forms.PolicyForm(request.POST or None, addon=addon)
    ctx.update(policy_form=policy_form)
    fs.append(policy_form)

    def mail_user_changes(author, title, template_part, recipients):
        from amo.utils import send_mail

        t = loader.get_template(
            'users/email/{part}.ltxt'.format(part=template_part))
        send_mail(title,
                  t.render(Context({'author': author, 'addon': addon,
                                    'site_url': settings.SITE_URL})),
                  None, recipients, use_blacklist=False, real_email=True)

    if request.method == 'POST' and all([form.is_valid() for form in fs]):
        # Authors.
        authors = user_form.save(commit=False)
        addon_authors_emails = list(
            addon.authors.values_list('email', flat=True))
        authors_emails = set(addon_authors_emails +
                             [author.user.email for author in authors])
        for author in authors:
            action = None
            if not author.id or author.user_id != author._original_user_id:
                action = amo.LOG.ADD_USER_WITH_ROLE
                author.addon = addon
                mail_user_changes(
                    author=author,
                    title=_('An author has been added to your add-on'),
                    template_part='author_added',
                    recipients=authors_emails)
            elif author.role != author._original_role:
                action = amo.LOG.CHANGE_USER_WITH_ROLE
                mail_user_changes(
                    author=author,
                    title=_('An author has a role changed on your add-on'),
                    template_part='author_changed',
                    recipients=authors_emails)

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
            authors_emails.add(author.user.email)
            mail_user_changes(
                author=author,
                title=_('An author has been removed from your add-on'),
                template_part='author_removed',
                recipients=authors_emails)

        if license_form in fs:
            license_form.save()
        if policy_form in fs:
            policy_form.save()
        messages.success(request, _('Changes successfully saved.'))

        return redirect(addon.get_dev_url('owner'))

    ctx.update(addon=addon, user_form=user_form)
    return render(request, 'devhub/addons/owner.html', ctx)


@dev_required(owner_for_post=True)
def payments(request, addon_id, addon):
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

    return render(request, 'devhub/payments/payments.html',
                  dict(addon=addon, errors=errors, charity_form=charity_form,
                       contrib_form=contrib_form, profile_form=profile_form))


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


@dev_required
@post_required
def disable_payments(request, addon_id, addon):
    addon.update(wants_contributions=False)
    return redirect(addon.get_dev_url('payments'))


@dev_required
@post_required
def remove_profile(request, addon_id, addon):
    delete_translation(addon, 'the_reason')
    delete_translation(addon, 'the_future')
    if addon.wants_contributions:
        addon.update(wants_contributions=False)
    return redirect(addon.get_dev_url('profile'))


@dev_required
def profile(request, addon_id, addon):
    profile_form = forms.ProfileForm(request.POST or None, instance=addon)

    if request.method == 'POST' and profile_form.is_valid():
        profile_form.save()
        amo.log(amo.LOG.EDIT_PROPERTIES, addon)
        messages.success(request, _('Changes successfully saved.'))
        return redirect(addon.get_dev_url('profile'))

    return render(request, 'devhub/addons/profile.html',
                  dict(addon=addon, profile_form=profile_form))


@login_required
@post_required
@json_view
def compat_application_versions(request):
    app_id = request.POST['application']
    f = CheckCompatibilityForm()
    return {'choices': f.version_choices_for_app_id(app_id)}


@login_required
def validate_addon(request):
    return render(request, 'devhub/validate_addon.html',
                  {'title': _('Validate Add-on'),
                   'upload_url': reverse('devhub.standalone_upload')})


@login_required
def check_addon_compatibility(request):
    form = CheckCompatibilityForm()
    return render(request, 'devhub/validate_addon.html',
                  {'appversion_form': form,
                   'title': _('Check Add-on Compatibility'),
                   'upload_url': reverse('devhub.standalone_upload')})


@dev_required
@json_view
def file_perf_tests_start(request, addon_id, addon, file_id):
    if not waffle.flag_is_active(request, 'perf-tests'):
        raise PermissionDenied
    file_ = get_object_or_404(File, pk=file_id)

    plats = perf.PLATFORM_MAP.get(file_.platform, None)
    if plats is None:
        log.info('Unsupported performance platform %s for file %s'
                 % (file_.get_platform_display(), file_))
        # TODO(Kumar) provide a message about this
        return {'success': False}

    for app in perf.ALL_APPS:
        for plat in plats:
            tasks.start_perf_test_for_file.delay(file_.id, plat, app)
    return {'success': True}


@login_required
@post_required
@write
def upload(request, addon_slug=None, is_standalone=False):
    filedata = request.FILES['upload']

    fu = FileUpload.from_post(filedata, filedata.name, filedata.size)
    log.info('FileUpload created: %s' % fu.pk)
    if request.user.is_authenticated():
        fu.user = request.amo_user
        fu.save()
    app_id = request.POST.get('app_id')
    if app_id and request.POST.get('version_id'):
        app = amo.APPS_ALL.get(int(app_id))
        if not app:
            raise http.Http404()
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
        error_message = {'type': 'error',
                         'message': escape_all(error_text),
                         'tier': 1}

        v = {'errors': 1, 'success': False, 'messages': [error_message]}
        return {'validation': v, 'error': error_text}


@login_required
@post_required
def standalone_upload(request):
    return upload(request, is_standalone=True)


@login_required
@json_view
def standalone_upload_detail(request, uuid):
    upload = get_object_or_404(FileUpload, uuid=uuid)
    url = reverse('devhub.standalone_upload_detail', args=[uuid])
    return upload_validation_context(request, upload, url=url)


@post_required
@dev_required
def upload_for_addon(request, addon_id, addon):
    return upload(request, addon_slug=addon.slug)


@dev_required
@json_view
def upload_detail_for_addon(request, addon_id, addon, uuid):
    upload = get_object_or_404(FileUpload, uuid=uuid)
    return json_upload_detail(request, upload, addon_slug=addon.slug)


@dev_required(allow_editors=True)
def file_validation(request, addon_id, addon, file_id):
    file = get_object_or_404(File, id=file_id)

    v = reverse('devhub.json_file_validation', args=[addon.slug, file.id])
    return render(request, 'devhub/validation.html',
                  dict(validate_url=v, filename=file.filename,
                       timestamp=file.created, addon=addon))


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
        major = ver.split('.')[0]  # 4.0b3 -> 4
        change_links['%s %s' % (amo.APP_IDS[app].guid, ver)] = tpl % major
    return render(request, 'devhub/validation.html',
                  dict(validate_url=revalidate_url,
                       filename=validated_filename, timestamp=validated_ts,
                       target_app=target_app, target_version=target_version,
                       addon=for_addon, result_type='compat',
                       app_trans=app_trans, version_change_links=change_links))


@json_view
@csrf_exempt
@dev_required(allow_editors=True)
def json_file_validation(request, addon_id, addon, file_id):
    file = get_object_or_404(File, id=file_id)
    if not file.has_been_validated:
        if request.method != 'POST':
            return http.HttpResponseNotAllowed(['POST'])

        try:
            v_result = tasks.file_validator(file.id)
        except Exception, exc:
            log.error('file_validator(%s): %s' % (file.id, exc))
            error = "\n".join(traceback.format_exception(*sys.exc_info()))
            return make_validation_results({'validation': '', 'error': error})
    else:
        v_result = file.validation

    validation = json.loads(v_result.validation)
    return make_validation_results({'validation': validation, 'error': None})


@json_view
@csrf_exempt
@post_required
@dev_required(allow_editors=True)
def json_bulk_compat_result(request, addon_id, addon, result_id):
    qs = ValidationResult.objects.exclude(completed=None)
    result = get_object_or_404(qs, pk=result_id)
    if result.task_error:
        return make_validation_results({'validation': '',
                                        'error': result.task_error})
    else:
        validation = json.loads(result.validation)
        return make_validation_results({'validation': validation,
                                        'error': None})


@json_view
def json_upload_detail(request, upload, addon_slug=None):
    addon = None
    if addon_slug:
        addon = get_object_or_404(Addon, slug=addon_slug)
    result = upload_validation_context(request, upload, addon=addon)
    plat_exclude = []
    if result['validation']:
        try:
            pkg = parse_addon(upload, addon=addon)
        except django_forms.ValidationError, exc:
            errors_before = result['validation'].get('errors', 0)
            # FIXME: This doesn't guard against client-side
            # tinkering.
            for i, msg in enumerate(exc.messages):
                # Simulate a validation error so the UI displays
                # it as such
                result['validation']['messages'].insert(
                    i, {'type': 'error',
                        'message': escape_all(msg), 'tier': 1,
                        'fatal': True})
                if result['validation']['ending_tier'] < 1:
                    result['validation']['ending_tier'] = 1
                result['validation']['errors'] += 1

            if not errors_before:
                return json_view.error(result)
        else:
            app_ids = set([a.id for a in pkg.get('apps', [])])
            supported_platforms = []
            for app in (amo.MOBILE, amo.ANDROID):
                if app.id in app_ids:
                    supported_platforms.extend((amo.PLATFORM_ANDROID.id,))
                    app_ids.remove(app.id)
            if len(app_ids):
                # Targets any other non-mobile app:
                supported_platforms.extend(amo.DESKTOP_PLATFORMS.keys())
            s = amo.SUPPORTED_PLATFORMS.keys()
            plat_exclude = set(s) - set(supported_platforms)
            plat_exclude = [str(p) for p in plat_exclude]

            # Does the version number look like it's beta?
            result['beta'] = is_beta(pkg.get('version', ''))

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

    validation = upload.escaped_validation(
        is_compatibility=upload.compat_with_app)
    if not url:
        if addon:
            url = reverse('devhub.upload_detail_for_addon',
                          args=[addon.slug, upload.uuid])
        else:
            url = reverse('devhub.upload_detail', args=[upload.uuid, 'json'])
    full_report_url = reverse('devhub.upload_detail', args=[upload.uuid])

    return {'upload': upload.uuid,
            'validation': validation,
            'error': hide_traceback(upload.task_error),
            'url': url,
            'full_report_url': full_report_url}


@login_required
def upload_detail(request, uuid, format='html'):
    upload = get_object_or_404(FileUpload, uuid=uuid)

    if format == 'json' or request.is_ajax():
        return json_upload_detail(request, upload)

    validate_url = reverse('devhub.standalone_upload_detail',
                           args=[upload.uuid])
    if upload.compat_with_app:
        return _compat_result(request, validate_url,
                              upload.compat_with_app,
                              upload.compat_with_appver)
    return render(request, 'devhub/validation.html',
                  dict(validate_url=validate_url, filename=upload.name,
                       timestamp=upload.created))


class AddonDependencySearch(BaseAjaxSearch):
    # No personas.
    types = [amo.ADDON_ANY, amo.ADDON_EXTENSION, amo.ADDON_THEME,
             amo.ADDON_DICT, amo.ADDON_SEARCH, amo.ADDON_LPAPP]


@dev_required
@json_view
def ajax_dependencies(request, addon_id, addon):
    return AddonDependencySearch(request, excluded_ids=[addon_id]).items


@dev_required
def addons_section(request, addon_id, addon, section, editable=False):
    basic = addon_forms.AddonFormBasic
    models = {'basic': basic,
              'media': addon_forms.AddonFormMedia,
              'details': addon_forms.AddonFormDetails,
              'support': addon_forms.AddonFormSupport,
              'technical': addon_forms.AddonFormTechnical,
              'admin': forms.AdminForm}

    if section not in models:
        raise http.Http404()

    tags, previews, restricted_tags = [], [], []
    cat_form = dependency_form = None

    if section == 'basic':
        tags = addon.tags.not_blacklisted().values_list('tag_text', flat=True)
        cat_form = addon_forms.CategoryFormSet(request.POST or None,
                                               addon=addon, request=request)
        restricted_tags = addon.tags.filter(restricted=True)

    elif section == 'media':
        previews = forms.PreviewFormSet(
            request.POST or None,
            prefix='files', queryset=addon.previews.all())

    elif section == 'technical':
        dependency_form = forms.DependencyFormSet(
            request.POST or None,
            queryset=addon.addons_dependencies.all(), addon=addon,
            prefix='dependencies')

    # Get the slug before the form alters it to the form data.
    valid_slug = addon.slug
    if editable:
        if request.method == 'POST':
            if section == 'license':
                form = models[section](request.POST)
            else:
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
            if dependency_form:
                if dependency_form.is_valid():
                    dependency_form.save()
                else:
                    editable = True
        else:
            if section == 'license':
                form = models[section]()
            else:
                form = models[section](instance=addon, request=request)
    else:
        form = False

    url_prefix = 'addons'

    data = {'addon': addon,
            'url_prefix': url_prefix,
            'form': form,
            'editable': editable,
            'tags': tags,
            'restricted_tags': restricted_tags,
            'cat_form': cat_form,
            'preview_form': previews,
            'dependency_form': dependency_form,
            'valid_slug': valid_slug}

    return render(request, 'devhub/addons/edit/%s.html' % section, data)


@never_cache
@dev_required(theme=True)
@json_view
def image_status(request, addon_id, addon, theme=False):
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
def ajax_upload_image(request, upload_type, addon_id=None):
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
        if errors and upload_type == 'preview' and os.path.exists(loc):
            # Delete the temporary preview file in case of error.
            os.unlink(loc)
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
    version_form = forms.VersionForm(
        request.POST or None,
        request.FILES or None,
        instance=version
    )

    new_file_form = forms.NewFileForm(request.POST or None,
                                      addon=addon, version=version,
                                      request=request)

    file_form = forms.FileFormSet(request.POST or None, prefix='files',
                                  queryset=version.files.all())
    file_history = _get_file_history(version)

    data = {'version_form': version_form, 'file_form': file_form}

    is_admin = acl.action_allowed(request, 'ReviewerAdminTools', 'View')

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
                file_history=file_history, is_admin=is_admin)
    return render(request, 'devhub/versions/edit.html', data)


def _log_max_version_change(addon, version, appversion):
    details = {'version': version.version,
               'target': appversion.version.version,
               'application': appversion.application}
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
    if 'disable_version' in request.POST:
        messages.success(request, _('Version %s disabled.') % version.version)
        version.files.update(status=amo.STATUS_DISABLED)
        version.addon.update_status()
    else:
        messages.success(request, _('Version %s deleted.') % version.version)
        version.delete()
    return redirect(addon.get_dev_url('versions'))


def check_validation_override(request, form, addon, version):
    if version and form.cleaned_data.get('admin_override_validation'):
        helper = ReviewHelper(request=request, addon=addon, version=version)
        helper.set_data(
            dict(operating_systems='', applications='',
                 comments=_(u'This upload has failed validation, and may '
                            u'lack complete validation results. Please '
                            u'take due care when reviewing it.')))
        helper.actions['super']['method']()


@json_view
@dev_required
@post_required
def version_add(request, addon_id, addon):
    form = forms.NewVersionForm(
        request.POST,
        request.FILES,
        addon=addon,
        request=request
    )
    if form.is_valid():
        pl = form.cleaned_data.get('supported_platforms', [])
        v = Version.from_upload(
            upload=form.cleaned_data['upload'],
            addon=addon,
            platforms=pl,
            source=form.cleaned_data['source'],
            is_beta=form.cleaned_data['beta']
        )
        rejected_versions = addon.versions.filter(
            version=v.version, files__status=amo.STATUS_DISABLED)[:1]
        if not v.releasenotes and rejected_versions:
            # Let's reuse the release and approval notes from the previous
            # rejected version.
            last_rejected = rejected_versions[0]
            v.releasenotes = amo.utils.translations_for_field(
                last_rejected.releasenotes)
            v.approvalnotes = last_rejected.approvalnotes
            v.save()
        log.info('Version created: %s for: %s' %
                 (v.pk, form.cleaned_data['upload']))
        check_validation_override(request, form, addon, v)
        if (addon.status == amo.STATUS_NULL and
                form.cleaned_data['nomination_type']):
            addon.update(status=form.cleaned_data['nomination_type'])
        url = reverse('devhub.versions.edit', args=[addon.slug, str(v.id)])
        return dict(url=url)
    else:
        return json_view.error(form.errors)


@json_view
@dev_required
@post_required
def version_add_file(request, addon_id, addon, version_id):
    version = get_object_or_404(Version, pk=version_id, addon=addon)
    form = forms.NewFileForm(request.POST, request.FILES, addon=addon,
                             version=version, request=request)
    if not form.is_valid():
        return json_view.error(form.errors)
    upload = form.cleaned_data['upload']
    new_file = File.from_upload(upload, version, form.cleaned_data['platform'],
                                form.cleaned_data['beta'],
                                parse_addon(upload, addon))
    source = form.cleaned_data['source']
    if source:
        version.update(source=source)
    storage.delete(upload.path)
    check_validation_override(request, form, addon, new_file.version)
    file_form = forms.FileFormSet(prefix='files', queryset=version.files.all())
    form = [f for f in file_form.forms if f.instance == new_file]
    return render(request, 'devhub/includes/version_file.html',
                  {'form': form[0], 'addon': addon})


@dev_required
def version_list(request, addon_id, addon):
    qs = addon.versions.order_by('-created').transform(Version.transformer)
    versions = amo.utils.paginate(request, qs)
    new_file_form = forms.NewVersionForm(None, addon=addon, request=request)
    is_admin = acl.action_allowed(request, 'ReviewerAdminTools', 'View')

    data = {'addon': addon,
            'versions': versions,
            'new_file_form': new_file_form,
            'position': get_position(addon),
            'timestamp': int(time.time()),
            'is_admin': is_admin}
    return render(request, 'devhub/versions/list.html', data)


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
            max_step = 7
            # We only bounce on pages with an addon id.
            if 'addon' in kw:
                addon = kw['addon']
                on_step = SubmitStep.objects.filter(addon=addon)
                if on_step:
                    max_step = on_step[0].step
                    if max_step < step:
                        # The step was too high, so bounce to the saved step.
                        return redirect(_step_url(max_step), addon.slug)
                elif step != max_step:
                    # We couldn't find a step, so we must be done.
                    return redirect(_step_url(7), addon.slug)
            kw['step'] = Step(step, max_step)
            return f(request, *args, **kw)
        # Tell @dev_required that this is a function in the submit flow so it
        # doesn't try to redirect into the submit flow.
        wrapper.submitting = True
        return wrapper
    return decorator


def _step_url(step):
    url_base = 'devhub.submit'
    return '%s.%s' % (url_base, step)


@login_required
@submit_step(1)
def submit(request, step):
    if request.method == 'POST':
        request.user.update(read_dev_agreement=now())
        response = redirect(_step_url(2))
        response.set_cookie(DEV_AGREEMENT_COOKIE)
        return response

    return render(request, 'devhub/addons/submit/start.html', {'step': step})


@login_required
@submit_step(2)
def submit_addon(request, step):
    if DEV_AGREEMENT_COOKIE not in request.COOKIES:
        return redirect(_step_url(1))
    form = forms.NewAddonForm(
        request.POST or None,
        request.FILES or None,
        request=request
    )
    if request.method == 'POST':
        if form.is_valid():
            data = form.cleaned_data

            p = data.get('supported_platforms', [])

            addon = Addon.from_upload(data['upload'], p, source=data['source'],
                                      is_listed=data['is_listed'])
            AddonUser(addon=addon, user=request.amo_user).save()
            check_validation_override(request, form, addon,
                                      addon.current_version)
            next_step = 3
            if not addon.is_listed:  # Not listed? Skip straight to step 6.
                next_step = 6
                messages.info(
                    request,
                    _("Skipping to step 6 because the add-on won't be listed"))
            SubmitStep.objects.create(addon=addon, step=next_step)
            return redirect(_step_url(next_step), addon.slug)
    template = 'upload.html'
    is_admin = acl.action_allowed(request, 'ReviewerAdminTools', 'View')

    return render(request, 'devhub/addons/submit/%s' % template,
                  {'step': step, 'new_addon_form': form, 'is_admin': is_admin})


@dev_required
@submit_step(3)
def submit_describe(request, addon_id, addon, step):
    form_cls = forms.Step3Form
    form = form_cls(request.POST or None, instance=addon, request=request)
    cat_form = addon_forms.CategoryFormSet(request.POST or None, addon=addon,
                                           request=request)

    if request.method == 'POST' and form.is_valid() and cat_form.is_valid():
        addon = form.save(addon)
        cat_form.save()
        SubmitStep.objects.filter(addon=addon).update(step=4)
        return redirect(_step_url(4), addon.slug)
    return render(request, 'devhub/addons/submit/describe.html',
                  {'form': form, 'cat_form': cat_form, 'addon': addon,
                   'step': step})


@dev_required
@submit_step(4)
def submit_media(request, addon_id, addon, step):
    form_icon = addon_forms.AddonFormMedia(
        request.POST or None,
        request.FILES or None, instance=addon, request=request)
    form_previews = forms.PreviewFormSet(
        request.POST or None,
        prefix='files', queryset=addon.previews.all())

    if (request.method == 'POST' and
            form_icon.is_valid() and form_previews.is_valid()):
        addon = form_icon.save(addon)

        for preview in form_previews.forms:
            preview.save(addon)

        SubmitStep.objects.filter(addon=addon).update(step=5)

        return redirect(_step_url(5), addon.slug)

    return render(request, 'devhub/addons/submit/media.html',
                  {'form': form_icon, 'addon': addon, 'step': step,
                   'preview_form': form_previews})


@dev_required
@submit_step(5)
def submit_license(request, addon_id, addon, step):
    fs, ctx = [], {}
    # Versions.
    license_form = forms.LicenseForm(request.POST or None, addon=addon)
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
    ctx.update(addon=addon, policy_form=policy_form, step=step)

    return render(request, 'devhub/addons/submit/license.html', ctx)


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

    return render(request, 'devhub/addons/submit/select-review.html',
                  {'addon': addon, 'review_type_form': review_type_form,
                   'step': step})


@dev_required
@submit_step(7)
def submit_done(request, addon_id, addon, step):
    # Bounce to the versions page if they don't have any versions.
    if not addon.versions.exists():
        return redirect(addon.get_dev_url('versions'))
    sp = addon.current_version.supported_platforms
    is_platform_specific = sp != [amo.PLATFORM_ALL]

    try:
        author = addon.authors.all()[0]
    except IndexError:
        # This should never happen.
        author = None

    if author:
        submitted_addons = (author.addons
                            .exclude(status=amo.STATUS_NULL).count())
        if submitted_addons == 1:
            # We can use locale-prefixed URLs because the submitter probably
            # speaks the same language by the time he/she reads the email.
            context = {
                'app': unicode(request.APP.pretty),
                'detail_url': absolutify(addon.get_url_path()),
                'version_url': absolutify(addon.get_dev_url('versions')),
                'edit_url': absolutify(addon.get_dev_url('edit')),
                'full_review': addon.status == amo.STATUS_NOMINATED
            }
            tasks.send_welcome_email.delay(addon.id, [author.email], context)

    return render(request, 'devhub/addons/submit/done.html',
                  {'addon': addon, 'step': step,
                   'is_platform_specific': is_platform_specific})


@dev_required
def submit_resume(request, addon_id, addon):
    step = SubmitStep.objects.filter(addon=addon)
    return _resume(addon, step)


def _resume(addon, step):
    if step:
        return redirect(_step_url(step[0].step), addon.slug)

    return redirect(addon.get_dev_url('versions'))


@login_required
@dev_required
def submit_bump(request, addon_id, addon):
    if not acl.action_allowed(request, 'Admin', 'EditSubmitStep'):
        raise PermissionDenied
    step = SubmitStep.objects.filter(addon=addon)
    step = step[0] if step else None
    if request.method == 'POST' and request.POST.get('step'):
        new_step = request.POST['step']
        if step:
            step.step = new_step
        else:
            step = SubmitStep(addon=addon, step=new_step)
        step.save()
        return redirect(_step_url('bump'), addon.slug)
    return render(request, 'devhub/addons/submit/bump.html',
                  dict(addon=addon, step=step))


@login_required
def submit_theme(request):
    data = {}
    if request.method == 'POST':
        data = request.POST.dict()
        if 'unsaved_data' in request.session and data['unsaved_data'] == '{}':
            # Restore unsaved data on second invalid POST..
            data['unsaved_data'] = request.session['unsaved_data']

    form = addon_forms.ThemeForm(data=data or None,
                                 files=request.FILES or None,
                                 request=request)

    if request.method == 'POST':
        if form.is_valid():
            addon = form.save()
            return redirect('devhub.themes.submit.done', addon.slug)
        else:
            # Stored unsaved data in request.session since it gets lost on
            # second invalid POST.
            messages.error(request, _('Please check the form for errors.'))
            request.session['unsaved_data'] = data['unsaved_data']

    return render(request, 'devhub/personas/submit.html', dict(form=form))


@dev_required(theme=True)
def submit_theme_done(request, addon_id, addon, theme):
    if addon.is_public():
        return redirect(addon.get_url_path())
    return render(request, 'devhub/personas/submit_done.html',
                  dict(addon=addon))


@dev_required(theme=True)
@post_required
def remove_locale(request, addon_id, addon, theme):
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
        raise PermissionDenied
    form = forms.AdminForm(request, request.POST or None, instance=addon)
    if form.is_valid():
        form.save()
    return render(request, 'devhub/addons/edit/admin.html',
                  {'addon': addon, 'admin_form': form})


def docs(request, doc_name=None):
    mdn_docs = {
        None: '',
        'getting-started': '',
        'reference': '',
        'how-to': '',
        'how-to/getting-started': '',
        'how-to/extension-development': '#Extensions',
        'how-to/other-addons': '#Other_types_of_add-ons',
        'how-to/thunderbird-mobile': '#Application-specific',
        'how-to/theme-development': '#Themes',
        'themes': '/Themes/Background',
        'themes/faq': '/Themes/Background/FAQ',
    }
    if waffle.switch_is_active('mdn-policy-docs'):
        mdn_docs.update({
            'policies': '/AMO/Policy',
            'policies/submission': '/AMO/Policy/Submission',
            'policies/reviews': '/AMO/Policy/Reviews',
            'policies/maintenance': '/AMO/Policy/Maintenance',
            'policies/recommended': '/AMO/Policy/Featured',
            'policies/contact': '/AMO/Policy/Contact',
        })
    if waffle.switch_is_active('mdn-agreement-docs'):
        # This will most likely depend on MDN being able to protect
        # pages.
        mdn_docs.update({
            'policies/agreement': '/AMO/Policy/Agreement',
        })

    all_docs = ('policies',
                'policies/submission',
                'policies/reviews',
                'policies/maintenance',
                'policies/recommended',
                'policies/agreement',
                'policies/contact')

    if doc_name in mdn_docs:
        return redirect(MDN_BASE + mdn_docs[doc_name],
                        permanent=True)

    if doc_name in all_docs:
        filename = '%s.html' % doc_name.replace('/', '-')
        return render(request, 'devhub/docs/%s' % filename)

    raise http.Http404()


def known_libraries(request, format=None):
    library_data = tasks.get_libraries()
    library_types = (
        ('libraries', _('Libraries')),
        ('frameworks', _('Add-on Frameworks')),
    )

    def sort_versions(v):
        return sorted(v, key=lambda t: version_int(t[0]))

    return render(request, 'devhub/known_libraries.html',
                  {'library_data': library_data,
                   'library_types': library_types,
                   'sort_versions': sort_versions})


@json_view
def known_libraries_json(request):
    return tasks.get_libraries()


def search(request):
    query = request.GET.get('q', '')
    return render(request, 'devhub/devhub_search.html', {'query': query})
