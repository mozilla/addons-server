import datetime
import json
import os
import time

from uuid import UUID, uuid4

from django import forms as django_forms, http
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage as storage
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.template import loader
from django.utils.translation import ugettext, ugettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

import waffle

from django_statsd.clients import statsd
from PIL import Image

import olympia.core.logger

from olympia import amo
from olympia.access import acl
from olympia.accounts.utils import redirect_for_login
from olympia.accounts.views import API_TOKEN_COOKIE
from olympia.activity.models import ActivityLog, VersionLog
from olympia.activity.utils import log_and_notify
from olympia.addons import forms as addon_forms
from olympia.addons.decorators import addon_view
from olympia.addons.models import Addon, AddonReviewerFlags, AddonUser
from olympia.addons.views import BaseFilter
from olympia.amo import messages, utils as amo_utils
from olympia.amo.decorators import json_view, login_required, post_required
from olympia.amo.templatetags.jinja_helpers import absolutify, urlparams
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import MenuItem, escape_all, render, send_mail
from olympia.api.models import APIKey
from olympia.applications.models import AppVersion
from olympia.devhub.decorators import dev_required, no_admin_disabled
from olympia.devhub.forms import AgreementForm, CheckCompatibilityForm
from olympia.devhub.models import BlogPost, RssKey
from olympia.devhub.utils import process_validation
from olympia.files.models import File, FileUpload, FileValidation
from olympia.files.utils import parse_addon
from olympia.lib.crypto.packaged import sign_file
from olympia.reviewers.forms import PublicWhiteboardForm
from olympia.reviewers.models import Whiteboard
from olympia.reviewers.templatetags.jinja_helpers import get_position
from olympia.reviewers.utils import ReviewHelper
from olympia.search.views import BaseAjaxSearch
from olympia.users.models import UserProfile
from olympia.versions import compare
from olympia.versions.models import Version
from olympia.zadmin.models import ValidationResult, get_config

from . import feeds, forms, signals, tasks


# We use a session cookie to make sure people see the dev agreement.

MDN_BASE = 'https://developer.mozilla.org/en-US/Add-ons'


def get_fileupload_by_uuid_or_404(value):
    try:
        UUID(value)
    except ValueError:
        raise http.Http404()
    return get_object_or_404(FileUpload, uuid=value)


class AddonFilter(BaseFilter):
    opts = (('updated', _(u'Updated')),
            ('name', _(u'Name')),
            ('created', _(u'Created')),
            ('popular', _(u'Downloads')),
            ('rating', _(u'Rating')))


class ThemeFilter(BaseFilter):
    opts = (('created', _(u'Created')),
            ('name', _(u'Name')),
            ('popular', _(u'Downloads')),
            ('rating', _(u'Rating')))


def addon_listing(request, theme=False):
    """Set up the queryset and filtering for addon listing for Dashboard."""
    if theme:
        qs = request.user.addons.filter(
            type__in=[amo.ADDON_PERSONA, amo.ADDON_STATICTHEME])
        filter_cls = ThemeFilter
        default = 'created'
    else:
        qs = Addon.objects.filter(authors=request.user).exclude(
            type__in=[amo.ADDON_PERSONA, amo.ADDON_STATICTHEME])
        filter_cls = AddonFilter
        default = 'updated'
    filter_ = filter_cls(request, qs, 'sort', default)
    return filter_.qs, filter_


def index(request):
    ctx = {'blog_posts': _get_posts()}
    if request.user.is_authenticated():
        user_addons = Addon.objects.filter(authors=request.user)
        recent_addons = user_addons.order_by('-modified')[:3]
        ctx['recent_addons'] = []
        for addon in recent_addons:
            ctx['recent_addons'].append({'addon': addon,
                                         'position': get_position(addon)})

    return render(request, 'devhub/index.html', ctx)


@login_required
def dashboard(request, theme=False):
    addon_items = _get_items(
        None, Addon.objects.filter(authors=request.user))[:4]

    data = dict(rss=_get_rss_feed(request), blog_posts=_get_posts(),
                timestamp=int(time.time()), addon_tab=not theme,
                theme=theme, addon_items=addon_items)
    if data['addon_tab']:
        addons, data['filter'] = addon_listing(request)
        # We know the dashboard is going to want to display feature
        # compatibility. Unfortunately, cache-machine doesn't obey
        # select_related properly, so to avoid the extra queries we do the next
        # best thing, prefetch_related, which works fine with cache-machine.
        addons = addons.prefetch_related('addonfeaturecompatibility')
        data['addons'] = amo_utils.paginate(request, addons, per_page=10)

    if theme:
        themes, data['filter'] = addon_listing(request, theme=True)
        data['themes'] = amo_utils.paginate(request, themes, per_page=10)

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
    version = get_object_or_404(Version.objects, pk=version_id, addon=addon)
    compat_form = forms.CompatFormSet(request.POST or None,
                                      queryset=version.apps.all(),
                                      form_kwargs={'version': version})
    if request.method == 'POST' and compat_form.is_valid():
        for compat in compat_form.save(commit=False):
            compat.version = version
            compat.save()

        for compat in compat_form.deleted_objects:
            compat.delete()

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
    (a.text, a.url) = (ugettext('All My Add-ons'), reverse('devhub.feed_all'))
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
    text = {None: ugettext('All Activity'),
            'updates': ugettext('Add-on Updates'),
            'status': ugettext('Add-on Status'),
            'collections': ugettext('User Collections'),
            'reviews': ugettext('User Reviews'),
            }

    items = []
    for c in choices:
        i = MenuItem()
        i.text = text[c]
        i.url, i.selected = urlparams(url, page=None, action=c), (action == c)
        items.append(i)

    return items


def _get_items(action, addons):
    filters = {
        'updates': (amo.LOG.ADD_VERSION, amo.LOG.ADD_FILE_TO_VERSION),
        'status': (amo.LOG.USER_DISABLE, amo.LOG.USER_ENABLE,
                   amo.LOG.CHANGE_STATUS, amo.LOG.APPROVE_VERSION,),
        'collections': (amo.LOG.ADD_TO_COLLECTION,
                        amo.LOG.REMOVE_FROM_COLLECTION,),
        'reviews': (amo.LOG.ADD_RATING,)
    }

    filter_ = filters.get(action)
    items = (ActivityLog.objects.for_addons(addons)
                        .exclude(action__in=amo.LOG_HIDE_DEVELOPER))
    if filter_:
        items = items.filter(action__in=[i.id for i in filter_])

    return items


def _get_rss_feed(request):
    key, __ = RssKey.objects.get_or_create(user=request.user)
    return urlparams(reverse('devhub.feed_all'), privaterss=key.key)


def feed(request, addon_id=None):
    if request.GET.get('privaterss'):
        return feeds.ActivityFeedRSS()(request)

    addon_selected = None

    if not request.user.is_authenticated():
        return redirect_for_login(request)
    else:
        addons_all = Addon.objects.filter(authors=request.user)

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

            if not acl.check_addon_ownership(request, addons, dev=True,
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

    pager = amo_utils.paginate(request, items, 20)
    data = dict(addons=addon_items, pager=pager, activities=activities,
                rss=rssurl, addon=addon)
    return render(request, 'devhub/addons/activity.html', data)


@dev_required
def edit(request, addon_id, addon):
    try:
        whiteboard = Whiteboard.objects.get(pk=addon.pk)
    except Whiteboard.DoesNotExist:
        whiteboard = Whiteboard(pk=addon.pk)

    data = {
        'page': 'edit',
        'addon': addon,
        'whiteboard': whiteboard,
        'editable': False,
        'show_listed_fields': addon.has_listed_versions(),
        'valid_slug': addon.slug,
        'tags': addon.tags.not_denied().values_list('tag_text', flat=True),
        'previews': addon.previews.all(),
        'supported_image_types': amo.SUPPORTED_IMAGE_TYPES,
    }

    if acl.action_allowed(request, amo.permissions.ADDONS_CONFIGURE):
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
                messages.success(
                    request, ugettext('Changes successfully saved.'))
                return redirect('devhub.themes.edit', addon.slug)
        elif form.is_valid():
            form.save()
            messages.success(request, ugettext('Changes successfully saved.'))
            return redirect('devhub.themes.edit', addon.reload().slug)
        else:
            messages.error(
                request, ugettext('Please check the form for errors.'))

    return render(request, 'devhub/personas/edit.html', {
        'addon': addon, 'persona': addon.persona, 'form': form,
        'owner_form': owner_form})


@dev_required(owner_for_post=True, theme=True)
@post_required
def delete(request, addon_id, addon, theme=False):
    # Database deletes only allowed for free or incomplete addons.
    if not addon.can_be_deleted():
        msg = ugettext(
            'Add-on cannot be deleted. Disable this add-on instead.')
        messages.error(request, msg)
        return redirect(addon.get_dev_url('versions'))

    form = forms.DeleteForm(request.POST, addon=addon)
    if form.is_valid():
        reason = form.cleaned_data.get('reason', '')
        addon.delete(msg='Removed via devhub', reason=reason)
        messages.success(
            request,
            ugettext('Theme deleted.')
            if theme else ugettext('Add-on deleted.'))
        return redirect('devhub.%s' % ('themes' if theme else 'addons'))
    else:
        if theme:
            messages.error(
                request,
                ugettext('URL name was incorrect. Theme was not deleted.'))
            return redirect(addon.get_dev_url())
        else:
            messages.error(
                request,
                ugettext('URL name was incorrect. Add-on was not deleted.'))
            return redirect(addon.get_dev_url('versions'))


@dev_required
@post_required
def enable(request, addon_id, addon):
    addon.update(disabled_by_user=False)
    ActivityLog.create(amo.LOG.USER_ENABLE, addon)
    return redirect(addon.get_dev_url('versions'))


@dev_required(owner_for_post=True)
@post_required
def cancel(request, addon_id, addon):
    if addon.status == amo.STATUS_NOMINATED:
        addon.update(status=amo.STATUS_NULL)
        ActivityLog.create(amo.LOG.CHANGE_STATUS, addon, addon.status)
    latest_version = addon.find_latest_version(
        channel=amo.RELEASE_CHANNEL_LISTED)
    if latest_version:
        for file_ in latest_version.files.filter(
                status=amo.STATUS_AWAITING_REVIEW):
            file_.update(status=amo.STATUS_DISABLED)
    return redirect(addon.get_dev_url('versions'))


@dev_required
@post_required
def disable(request, addon_id, addon):
    # Also set the latest listed version to STATUS_DISABLED if it was
    # AWAITING_REVIEW, to not waste reviewers time.
    latest_version = addon.find_latest_version(
        channel=amo.RELEASE_CHANNEL_LISTED)
    if latest_version:
        latest_version.files.filter(
            status=amo.STATUS_AWAITING_REVIEW).update(
            status=amo.STATUS_DISABLED)
    addon.update_version()
    addon.update_status()
    addon.update(disabled_by_user=True)
    ActivityLog.create(amo.LOG.USER_DISABLE, addon)
    return redirect(addon.get_dev_url('versions'))


@dev_required(owner_for_post=True)
def ownership(request, addon_id, addon):
    fs, ctx = [], {}
    post_data = request.POST if request.method == 'POST' else None
    # Authors.
    qs = AddonUser.objects.filter(addon=addon).order_by('position')
    user_form = forms.AuthorFormSet(post_data, queryset=qs)
    fs.append(user_form)
    # Versions.
    license_form = forms.LicenseForm(post_data, version=addon.current_version)
    ctx.update(license_form.get_context())
    if ctx['license_form']:  # if addon has a version
        fs.append(ctx['license_form'])
    # Policy.
    if addon.type != amo.ADDON_STATICTHEME:
        policy_form = forms.PolicyForm(post_data, addon=addon)
        ctx.update(policy_form=policy_form)
        fs.append(policy_form)
    else:
        policy_form = None

    def mail_user_changes(author, title, template_part, recipients):
        from olympia.amo.utils import send_mail

        t = loader.get_template(
            'users/email/{part}.ltxt'.format(part=template_part))
        send_mail(title,
                  t.render({'author': author, 'addon': addon,
                            'site_url': settings.SITE_URL}),
                  None, recipients, use_deny_list=False)

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
                    title=ugettext('An author has been added to your add-on'),
                    template_part='author_added',
                    recipients=authors_emails)
            elif author.role != author._original_role:
                action = amo.LOG.CHANGE_USER_WITH_ROLE
                title = ugettext('An author has a role changed on your add-on')
                mail_user_changes(
                    author=author,
                    title=title,
                    template_part='author_changed',
                    recipients=authors_emails)

            author.save()
            if action:
                ActivityLog.create(action, author.user,
                                   author.get_role_display(), addon)
            if (author._original_user_id and
                    author.user_id != author._original_user_id):
                ActivityLog.create(amo.LOG.REMOVE_USER_WITH_ROLE,
                                   (UserProfile, author._original_user_id),
                                   author.get_role_display(), addon)

        for author in user_form.deleted_objects:
            author.delete()
            ActivityLog.create(amo.LOG.REMOVE_USER_WITH_ROLE, author.user,
                               author.get_role_display(), addon)
            authors_emails.add(author.user.email)
            mail_user_changes(
                author=author,
                title=ugettext('An author has been removed from your add-on'),
                template_part='author_removed',
                recipients=authors_emails)

        if license_form in fs:
            license_form.save()
        if policy_form and policy_form in fs:
            policy_form.save()
        messages.success(request, ugettext('Changes successfully saved.'))

        return redirect(addon.get_dev_url('owner'))

    ctx.update(addon=addon, user_form=user_form)
    return render(request, 'devhub/addons/owner.html', ctx)


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
                  {'title': ugettext('Validate Add-on'),
                   'new_addon_form': forms.DistributionChoiceForm()})


@login_required
def check_addon_compatibility(request):
    form = CheckCompatibilityForm()
    return render(request, 'devhub/validate_addon.html',
                  {'appversion_form': form,
                   'title': ugettext('Check Add-on Compatibility'),
                   'new_addon_form': forms.DistributionChoiceForm()})


def handle_upload(filedata, request, channel, app_id=None, version_id=None,
                  addon=None, is_standalone=False, submit=False):
    automated_signing = channel == amo.RELEASE_CHANNEL_UNLISTED

    user = request.user if request.user.is_authenticated() else None
    upload = FileUpload.from_post(
        filedata, filedata.name, filedata.size,
        automated_signing=automated_signing, addon=addon, user=user)
    log.info('FileUpload created: %s' % upload.uuid.hex)
    if app_id and version_id:
        # If app_id and version_id are present, we are dealing with a
        # compatibility check (i.e. this is not an upload meant for submission,
        # we were called from check_addon_compatibility()), which essentially
        # consists in running the addon uploaded against the legacy validator
        # with a specific min/max appversion override.
        app = amo.APPS_ALL.get(int(app_id))
        if not app:
            raise http.Http404()
        ver = get_object_or_404(AppVersion, pk=version_id)
        tasks.compatibility_check.delay(upload.pk, app.guid, ver.version)
    elif submit:
        tasks.validate_and_submit(addon, upload, channel=channel)
    else:
        tasks.validate(upload, listed=(channel == amo.RELEASE_CHANNEL_LISTED))

    return upload


@login_required
@post_required
def upload(request, channel='listed', addon=None, is_standalone=False):
    channel = amo.CHANNEL_CHOICES_LOOKUP[channel]
    filedata = request.FILES['upload']
    app_id = request.POST.get('app_id')
    version_id = request.POST.get('version_id')
    upload = handle_upload(
        filedata=filedata, request=request, app_id=app_id,
        version_id=version_id, addon=addon, is_standalone=is_standalone,
        channel=channel)
    if addon:
        return redirect('devhub.upload_detail_for_version',
                        addon.slug, upload.uuid.hex)
    elif is_standalone:
        return redirect('devhub.standalone_upload_detail', upload.uuid.hex)
    else:
        return redirect('devhub.upload_detail', upload.uuid.hex, 'json')


@post_required
@dev_required
def upload_for_version(request, addon_id, addon, channel):
    return upload(request, channel=channel, addon=addon)


@login_required
@json_view
def standalone_upload_detail(request, uuid):
    upload = get_fileupload_by_uuid_or_404(uuid)
    url = reverse('devhub.standalone_upload_detail', args=[uuid])
    return upload_validation_context(request, upload, url=url)


@dev_required(submitting=True)
@json_view
def upload_detail_for_version(request, addon_id, addon, uuid):
    try:
        upload = get_fileupload_by_uuid_or_404(uuid)
        response = json_upload_detail(request, upload, addon_slug=addon.slug)
        statsd.incr('devhub.upload_detail_for_addon.success')
        return response
    except Exception as exc:
        statsd.incr('devhub.upload_detail_for_addon.error')
        log.error('Error checking upload status: {} {}'.format(type(exc), exc))
        raise


@dev_required(allow_reviewers=True)
def file_validation(request, addon_id, addon, file_id):
    file_ = get_object_or_404(File, id=file_id)

    validate_url = reverse('devhub.json_file_validation',
                           args=[addon.slug, file_.id])
    file_url = reverse('files.list', args=[file_.id, 'file', ''])

    context = {'validate_url': validate_url, 'file_url': file_url,
               'file': file_, 'filename': file_.filename,
               'timestamp': file_.created, 'addon': addon,
               'automated_signing': file_.automated_signing}

    if file_.has_been_validated:
        context['validation_data'] = file_.validation.processed_validation

    return render(request, 'devhub/validation.html', context)


@dev_required(allow_reviewers=True)
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
@dev_required(allow_reviewers=True)
def json_file_validation(request, addon_id, addon, file_id):
    file = get_object_or_404(File, id=file_id)
    try:
        result = file.validation
    except FileValidation.DoesNotExist:
        if request.method != 'POST':
            return http.HttpResponseNotAllowed(['POST'])

        # This API is, unfortunately, synchronous, so wait for the
        # task to complete and return the result directly.
        result = tasks.validate(file, synchronous=True).get()

    return {'validation': result.processed_validation, 'error': None}


@json_view
@csrf_exempt
@post_required
@dev_required(allow_reviewers=True)
def json_bulk_compat_result(request, addon_id, addon, result_id):
    result = get_object_or_404(ValidationResult, pk=result_id,
                               completed__isnull=False)

    validation = json.loads(result.validation)
    return {'validation': process_validation(validation), 'error': None}


@json_view
def json_upload_detail(request, upload, addon_slug=None):
    addon = None
    if addon_slug:
        addon = get_object_or_404(Addon.objects, slug=addon_slug)
    result = upload_validation_context(request, upload, addon=addon)
    plat_exclude = []
    if result['validation']:
        try:
            pkg = parse_addon(upload, addon=addon, user=request.user)
        except django_forms.ValidationError as exc:
            errors_before = result['validation'].get('errors', 0)
            # This doesn't guard against client-side tinkering, and is purely
            # to display those non-linter errors nicely in the frontend. What
            # does prevent clients from bypassing those is the fact that we
            # always call parse_addon() before calling from_upload(), so
            # ValidationError would be raised before proceeding.
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
            if amo.ANDROID.id in app_ids:
                supported_platforms.extend((amo.PLATFORM_ANDROID.id,))
                app_ids.remove(amo.ANDROID.id)
            if len(app_ids):
                # Targets any other non-mobile app:
                supported_platforms.extend(amo.DESKTOP_PLATFORMS.keys())
            plat_exclude = (
                set(amo.SUPPORTED_PLATFORMS.keys()) - set(supported_platforms))
            plat_exclude = [str(p) for p in plat_exclude]

            result['addon_type'] = pkg.get('type', '')

    result['platforms_to_exclude'] = plat_exclude
    return result


def upload_validation_context(request, upload, addon=None, url=None):
    if not url:
        if addon:
            url = reverse('devhub.upload_detail_for_version',
                          args=[addon.slug, upload.uuid.hex])
        else:
            url = reverse(
                'devhub.upload_detail',
                args=[upload.uuid.hex, 'json'])
    full_report_url = reverse('devhub.upload_detail', args=[upload.uuid.hex])

    validation = upload.processed_validation or ''

    processed_by_linter = (
        validation and
        validation.get('metadata', {}).get(
            'processed_by_addons_linter', False))

    return {'upload': upload.uuid.hex,
            'validation': validation,
            'error': None,
            'url': url,
            'full_report_url': full_report_url,
            'processed_by_addons_linter': processed_by_linter}


def upload_detail(request, uuid, format='html'):
    upload = get_fileupload_by_uuid_or_404(uuid)
    if upload.user_id and not request.user.is_authenticated():
        return redirect_for_login(request)

    if format == 'json' or request.is_ajax():
        try:
            response = json_upload_detail(request, upload)
            statsd.incr('devhub.upload_detail.success')
            return response
        except Exception as exc:
            statsd.incr('devhub.upload_detail.error')
            log.error('Error checking upload status: {} {}'.format(
                type(exc), exc))
            raise

    validate_url = reverse('devhub.standalone_upload_detail',
                           args=[upload.uuid.hex])

    if upload.compat_with_app:
        return _compat_result(request, validate_url,
                              upload.compat_with_app,
                              upload.compat_with_appver)

    context = {'validate_url': validate_url, 'filename': upload.pretty_name,
               'automated_signing': upload.automated_signing,
               'timestamp': upload.created}

    if upload.validation:
        context['validation_data'] = upload.processed_validation

    return render(request, 'devhub/validation.html', context)


class AddonDependencySearch(BaseAjaxSearch):
    # No personas.
    types = [amo.ADDON_EXTENSION, amo.ADDON_THEME, amo.ADDON_DICT,
             amo.ADDON_SEARCH, amo.ADDON_LPAPP]


@dev_required
@json_view
def ajax_dependencies(request, addon_id, addon):
    return AddonDependencySearch(request, excluded_ids=[addon_id]).items


@dev_required
def addons_section(request, addon_id, addon, section, editable=False):
    show_listed = addon.has_listed_versions()
    static_theme = addon.type == amo.ADDON_STATICTHEME
    models = {'admin': forms.AdminForm}
    if show_listed:
        models.update({
            'basic': addon_forms.AddonFormBasic,
            'details': addon_forms.AddonFormDetails,
            'support': addon_forms.AddonFormSupport,
            'technical': addon_forms.AddonFormTechnical
        })
        if not static_theme:
            models.update({'media': addon_forms.AddonFormMedia})
    else:
        models.update({
            'basic': addon_forms.AddonFormBasicUnlisted,
            'details': addon_forms.AddonFormDetailsUnlisted,
            'technical': addon_forms.AddonFormTechnicalUnlisted
        })

    if section not in models:
        raise http.Http404()

    tags, previews, restricted_tags = [], [], []
    cat_form = dependency_form = whiteboard_form = None
    whiteboard = None

    if section == 'basic' and show_listed:
        tags = addon.tags.not_denied().values_list('tag_text', flat=True)
        category_form_class = (forms.SingleCategoryForm if static_theme else
                               addon_forms.CategoryFormSet)
        cat_form = category_form_class(
            request.POST or None, addon=addon, request=request)
        restricted_tags = addon.tags.filter(restricted=True)

    elif section == 'media':
        previews = forms.PreviewFormSet(
            request.POST or None,
            prefix='files', queryset=addon.previews.all())

    elif section == 'technical' and show_listed and not static_theme:
        dependency_form = forms.DependencyFormSet(
            request.POST or None,
            queryset=addon.addons_dependencies.all(), addon=addon,
            prefix='dependencies')

    if section == 'technical':
        try:
            whiteboard = Whiteboard.objects.get(pk=addon.pk)
        except Whiteboard.DoesNotExist:
            whiteboard = Whiteboard(pk=addon.pk)

        whiteboard_form = PublicWhiteboardForm(request.POST or None,
                                               instance=whiteboard,
                                               prefix='whiteboard')

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
                    ActivityLog.create(amo.LOG.CHANGE_ICON, addon)
                else:
                    ActivityLog.create(amo.LOG.EDIT_PROPERTIES, addon)

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
            if whiteboard_form:
                if whiteboard_form.is_valid():
                    whiteboard_form.save()
                else:
                    editable = True

        else:
            form = models[section](instance=addon, request=request)
    else:
        form = False

    data = {
        'addon': addon,
        'whiteboard': whiteboard,
        'show_listed_fields': show_listed,
        'form': form,
        'editable': editable,
        'tags': tags,
        'restricted_tags': restricted_tags,
        'cat_form': cat_form,
        'preview_form': previews,
        'dependency_form': dependency_form,
        'whiteboard_form': whiteboard_form,
        'valid_slug': valid_slug,
        'supported_image_types': amo.SUPPORTED_IMAGE_TYPES,
    }

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

        upload_hash = uuid4().hex
        loc = os.path.join(settings.TMP_PATH, upload_type, upload_hash)

        with storage.open(loc, 'wb') as fd:
            for chunk in upload_preview:
                fd.write(chunk)

        is_icon = upload_type == 'icon'
        is_persona = upload_type.startswith('persona_')

        check = amo_utils.ImageCheck(upload_preview)
        if (upload_preview.content_type not in amo.IMG_TYPES or
                not check.is_image()):
            if is_icon:
                errors.append(ugettext('Icons must be either PNG or JPG.'))
            else:
                errors.append(ugettext('Images must be either PNG or JPG.'))

        if check.is_animated():
            if is_icon:
                errors.append(ugettext('Icons cannot be animated.'))
            else:
                errors.append(ugettext('Images cannot be animated.'))

        max_size = None
        if is_icon:
            max_size = settings.MAX_ICON_UPLOAD_SIZE
        if is_persona:
            max_size = settings.MAX_PERSONA_UPLOAD_SIZE

        if max_size and upload_preview.size > max_size:
            if is_icon:
                errors.append(
                    ugettext('Please use images smaller than %dMB.')
                    % (max_size / 1024 / 1024 - 1))
            if is_persona:
                errors.append(
                    ugettext('Images cannot be larger than %dKB.')
                    % (max_size / 1024))

        if check.is_image() and is_persona:
            persona, img_type = upload_type.split('_')  # 'header' or 'footer'
            expected_size = amo.PERSONA_IMAGE_SIZES.get(img_type)[1]
            with storage.open(loc, 'rb') as fp:
                actual_size = Image.open(fp).size
            if actual_size != expected_size:
                # L10n: {0} is an image width (in pixels), {1} is a height.
                errors.append(ugettext('Image must be exactly {0} pixels '
                                       'wide and {1} pixels tall.')
                              .format(expected_size[0], expected_size[1]))
        if errors and upload_type == 'preview' and os.path.exists(loc):
            # Delete the temporary preview file in case of error.
            os.unlink(loc)
    else:
        errors.append(ugettext('There was an error uploading your preview.'))

    if errors:
        upload_hash = ''

    return {'upload_hash': upload_hash, 'errors': errors}


@dev_required
def upload_image(request, addon_id, addon, upload_type):
    return ajax_upload_image(request, upload_type)


@dev_required
def version_edit(request, addon_id, addon, version_id):
    version = get_object_or_404(Version.objects, pk=version_id, addon=addon)
    static_theme = addon.type == amo.ADDON_STATICTHEME
    version_form = forms.VersionForm(
        request.POST or None,
        request.FILES or None,
        instance=version,
        request=request,
    ) if not static_theme else None

    file_form = forms.FileFormSet(request.POST or None, prefix='files',
                                  queryset=version.files.all())

    data = {'file_form': file_form}
    if version_form:
        data['version_form'] = version_form

    is_admin = acl.action_allowed(request,
                                  amo.permissions.REVIEWS_ADMIN)

    if addon.accepts_compatible_apps():
        # We should be in no-caching land but this one stays cached for some
        # reason.
        qs = version.apps.all().no_cache()
        compat_form = forms.CompatFormSet(
            request.POST or None, queryset=qs,
            form_kwargs={'version': version})
        data['compat_form'] = compat_form

    if (request.method == 'POST' and
            all([form.is_valid() for form in data.values()])):
        data['file_form'].save()

        if 'compat_form' in data:
            for compat in data['compat_form'].save(commit=False):
                compat.version = version
                compat.save()

            for compat in data['compat_form'].deleted_objects:
                compat.delete()

            for form in data['compat_form'].forms:
                if (isinstance(form, forms.CompatForm) and
                        'max' in form.changed_data):
                    _log_max_version_change(addon, version, form.instance)

        if 'version_form' in data:
            # VersionForm.save() clear the pending info request if the
            # developer specifically asked for it, but we've got additional
            # things to do here that depend on it.
            had_pending_info_request = bool(addon.pending_info_request)
            data['version_form'].save()

            if 'approvalnotes' in version_form.changed_data:
                if had_pending_info_request:
                    log_and_notify(amo.LOG.APPROVAL_NOTES_CHANGED, None,
                                   request.user, version)
                else:
                    ActivityLog.create(amo.LOG.APPROVAL_NOTES_CHANGED,
                                       addon, version, request.user)

            if ('source' in version_form.changed_data and
                    version_form.cleaned_data['source']):
                AddonReviewerFlags.objects.update_or_create(
                    addon=addon, defaults={'needs_admin_code_review': True})
                if had_pending_info_request:
                    log_and_notify(amo.LOG.SOURCE_CODE_UPLOADED, None,
                                   request.user, version)
                else:
                    ActivityLog.create(amo.LOG.SOURCE_CODE_UPLOADED,
                                       addon, version, request.user)

        messages.success(request, ugettext('Changes successfully saved.'))
        return redirect('devhub.versions.edit', addon.slug, version_id)

    data.update(addon=addon, version=version,
                is_admin=is_admin, choices=File.STATUS_CHOICES)
    return render(request, 'devhub/versions/edit.html', data)


def _log_max_version_change(addon, version, appversion):
    details = {'version': version.version,
               'target': appversion.version.version,
               'application': appversion.application}
    ActivityLog.create(amo.LOG.MAX_APPVERSION_UPDATED,
                       addon, version, details=details)


@dev_required
@post_required
@transaction.atomic
def version_delete(request, addon_id, addon):
    version_id = request.POST.get('version_id')
    version = get_object_or_404(Version.objects, pk=version_id, addon=addon)
    if 'disable_version' in request.POST:
        messages.success(
            request,
            ugettext('Version %s disabled.') % version.version)
        version.is_user_disabled = True  # Will update the files/activity log.
        version.addon.update_status()
    else:
        messages.success(
            request,
            ugettext('Version %s deleted.') % version.version)
        version.delete()  # Will also activity log.
    return redirect(addon.get_dev_url('versions'))


@dev_required
@post_required
@transaction.atomic
def version_reenable(request, addon_id, addon):
    version_id = request.POST.get('version_id')
    version = get_object_or_404(Version.objects, pk=version_id, addon=addon)
    messages.success(
        request,
        ugettext('Version %s re-enabled.') % version.version)
    version.is_user_disabled = False  # Will update the files/activity log.
    version.addon.update_status()
    return redirect(addon.get_dev_url('versions'))


def check_validation_override(request, form, addon, version):
    if version and form.cleaned_data.get('admin_override_validation'):
        helper = ReviewHelper(request=request, addon=addon, version=version)
        helper.set_data({
            'operating_systems': '',
            'applications': '',
            'comments': ugettext(
                u'This upload has failed validation, and may '
                u'lack complete validation results. Please '
                u'take due care when reviewing it.')})
        helper.actions['super']['method']()


def auto_sign_file(file_):
    """If the file should be automatically reviewed and signed, do it."""
    addon = file_.version.addon

    if file_.is_experiment:  # See bug 1220097.
        ActivityLog.create(amo.LOG.EXPERIMENT_SIGNED, file_)
        sign_file(file_)
    elif file_.version.channel == amo.RELEASE_CHANNEL_UNLISTED:
        # Sign automatically without manual review.
        helper = ReviewHelper(request=None, addon=addon,
                              version=file_.version)
        # Provide the file to review/sign to the helper.
        helper.set_data({'addon_files': [file_],
                         'comments': 'automatic validation'})
        helper.handler.process_public()
        ActivityLog.create(amo.LOG.UNLISTED_SIGNED, file_)


def auto_sign_version(version, **kwargs):
    # Sign all the unapproved files submitted, one for each platform.
    for file_ in version.files.exclude(status=amo.STATUS_PUBLIC):
        auto_sign_file(file_, **kwargs)


@dev_required
def version_list(request, addon_id, addon):
    qs = addon.versions.order_by('-created').transform(Version.transformer)
    versions = amo_utils.paginate(request, qs)
    is_admin = acl.action_allowed(request,
                                  amo.permissions.REVIEWS_ADMIN)

    token = request.COOKIES.get(API_TOKEN_COOKIE, None)

    data = {'addon': addon,
            'versions': versions,
            'token': token,
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
    reviews = (qs.annotate(review_count=Count('ratings'))
               .values('id', 'version', 'review_count'))
    data = {v['id']: v for v in reviews}
    files = (
        qs.annotate(file_count=Count('files')).values_list('id', 'file_count'))
    for id_, file_count in files:
        # For backwards compatibility
        data[id_]['files'] = file_count
        data[id_]['reviews'] = data[id_].pop('review_count')
    return data


def get_next_version_number(addon):
    if not addon:
        return '1.0'
    last_version = Version.unfiltered.filter(addon=addon).last()
    version_int_parts = compare.dict_from_int(last_version.version_int)

    version_counter = 1
    while True:
        next_version = '%s.0' % (version_int_parts['major'] + version_counter)
        if not Version.unfiltered.filter(addon=addon,
                                         version=next_version).exists():
            return next_version
        else:
            version_counter += 1


@login_required
def submit_addon(request):
    return render_agreement(request, 'devhub/addons/submit/start.html',
                            'devhub.submit.distribution')


@dev_required
def submit_version_agreement(request, addon_id, addon):
    return render_agreement(
        request, 'devhub/addons/submit/start.html',
        reverse('devhub.submit.version', args=(addon.slug,)),
        submit_page='version')


@transaction.atomic
def _submit_distribution(request, addon, next_view):
    # Accept GET for the first load so we can preselect the channel.
    form = forms.DistributionChoiceForm(
        request.POST if request.method == 'POST' else
        request.GET if request.GET.get('channel') else None)

    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        args = [addon.slug] if addon else []
        args.append(data['channel'])
        return redirect(next_view, *args)
    return render(request, 'devhub/addons/submit/distribute.html',
                  {'distribution_form': form,
                   'submit_notification_warning':
                       get_config('submit_notification_warning'),
                   'submit_page': 'version' if addon else 'addon'})


@login_required
def submit_addon_distribution(request):
    if not request.user.has_read_developer_agreement():
        return redirect('devhub.submit.agreement')
    return _submit_distribution(request, None, 'devhub.submit.upload')


@dev_required(submitting=True)
def submit_version_distribution(request, addon_id, addon):
    if not request.user.has_read_developer_agreement():
        return redirect('devhub.submit.version.agreement', addon.slug)
    return _submit_distribution(request, addon, 'devhub.submit.version.upload')


@transaction.atomic
def _submit_upload(request, addon, channel, next_details, next_finish,
                   version=None, wizard=False):
    """ If this is a new addon upload `addon` will be None (and `version`);
    if this is a new version upload `version` will be None; a new file for a
    version will need both an addon and a version supplied.
    next_details is the view that will be redirected to when details are needed
    (for listed, addons/versions); next_finish is the finishing view
    when no details step is needed (for unlisted addons/versions).
    """
    form = forms.NewUploadForm(
        request.POST or None,
        request.FILES or None,
        addon=addon,
        version=version,
        request=request
    )
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data

        if version:
            for platform in data.get('supported_platforms', []):
                File.from_upload(
                    upload=data['upload'],
                    version=version,
                    platform=platform,
                    parsed_data=data['parsed_data'])
            url_args = [addon.slug, version.id]
        elif addon:
            version = Version.from_upload(
                upload=data['upload'],
                addon=addon,
                platforms=data.get('supported_platforms', []),
                channel=channel,
                source=data['source'],
                parsed_data=data['parsed_data'])
            url_args = [addon.slug, version.id]
        else:
            addon = Addon.from_upload(
                upload=data['upload'],
                platforms=data.get('supported_platforms', []),
                source=data['source'],
                channel=channel,
                parsed_data=data['parsed_data'],
                user=request.user)
            version = addon.find_latest_version(channel=channel)
            url_args = [addon.slug]

        check_validation_override(request, form, addon, version)
        if data.get('source'):
            AddonReviewerFlags.objects.update_or_create(
                addon=addon, defaults={'needs_admin_code_review': True})
            activity_log = ActivityLog.objects.create(
                action=amo.LOG.SOURCE_CODE_UPLOADED.id,
                user=request.user,
                details={
                    'comments': (u'This version has been automatically '
                                 u'flagged for admin review, as it had source '
                                 u'files attached when submitted.')})
            VersionLog.objects.create(version_id=version.id,
                                      activity_log=activity_log)
        if (addon.status == amo.STATUS_NULL and
                addon.has_complete_metadata() and
                channel == amo.RELEASE_CHANNEL_LISTED):
            addon.update(status=amo.STATUS_NOMINATED)
        # auto-sign versions (the method checks eligibility)
        auto_sign_version(version)
        next_url = (next_details
                    if channel == amo.RELEASE_CHANNEL_LISTED
                    else next_finish)
        return redirect(next_url, *url_args)
    is_admin = acl.action_allowed(request,
                                  amo.permissions.REVIEWS_ADMIN)
    if addon:
        channel_choice_text = (forms.DistributionChoiceForm().LISTED_LABEL
                               if channel == amo.RELEASE_CHANNEL_LISTED else
                               forms.DistributionChoiceForm().UNLISTED_LABEL)
    else:
        channel_choice_text = ''  # We only need this for Version upload.
    submit_page = 'file' if version else 'version' if addon else 'addon'
    template = ('devhub/addons/submit/upload.html' if not wizard else
                'devhub/addons/submit/wizard.html')
    return render(request, template,
                  {'new_addon_form': form,
                   'is_admin': is_admin,
                   'addon': addon,
                   'submit_notification_warning':
                       get_config('submit_notification_warning'),
                   'submit_page': submit_page,
                   'channel': channel,
                   'channel_choice_text': channel_choice_text,
                   'version_number':
                       get_next_version_number(addon) if wizard else None})


@login_required
def submit_addon_upload(request, channel):
    channel_id = amo.CHANNEL_CHOICES_LOOKUP[channel]
    return _submit_upload(request, None, channel_id,
                          'devhub.submit.details', 'devhub.submit.finish')


@dev_required(submitting=True)
@no_admin_disabled
def submit_version_upload(request, addon_id, addon, channel):
    channel_id = amo.CHANNEL_CHOICES_LOOKUP[channel]
    return _submit_upload(request, addon, channel_id,
                          'devhub.submit.version.details',
                          'devhub.submit.version.finish')


@dev_required
@no_admin_disabled
def submit_version_auto(request, addon_id, addon):
    if not request.user.has_read_developer_agreement():
        return redirect('devhub.submit.version.agreement', addon.slug)
    # choose the channel we need from the last upload
    last_version = addon.find_latest_version(None, exclude=())
    if not last_version:
        return redirect('devhub.submit.version.distribution', addon.slug)
    channel = last_version.channel
    return _submit_upload(request, addon, channel,
                          'devhub.submit.version.details',
                          'devhub.submit.version.finish')


@login_required
@waffle.decorators.waffle_switch('allow-static-theme-uploads')
def submit_addon_theme_wizard(request, channel):
    channel_id = amo.CHANNEL_CHOICES_LOOKUP[channel]
    return _submit_upload(request, None, channel_id,
                          'devhub.submit.details', 'devhub.submit.finish',
                          wizard=True)


@dev_required
@no_admin_disabled
@waffle.decorators.waffle_switch('allow-static-theme-uploads')
def submit_version_theme_wizard(request, addon_id, addon, channel):
    channel_id = amo.CHANNEL_CHOICES_LOOKUP[channel]
    return _submit_upload(request, addon, channel_id,
                          'devhub.submit.version.details',
                          'devhub.submit.version.finish', wizard=True)


@dev_required
def submit_file(request, addon_id, addon, version_id):
    version = get_object_or_404(Version, id=version_id)
    return _submit_upload(request, addon, version.channel,
                          'devhub.submit.file.finish',
                          'devhub.submit.file.finish',
                          version=version)


def _submit_details(request, addon, version):
    static_theme = addon.type == amo.ADDON_STATICTHEME
    if version:
        skip_details_step = (version.channel == amo.RELEASE_CHANNEL_UNLISTED or
                             (static_theme and addon.has_complete_metadata()))
        if skip_details_step:
            # Nothing to do here.
            return redirect(
                'devhub.submit.version.finish', addon.slug, version.pk)
        latest_version = version
    else:
        # Figure out the latest version early in order to pass the same
        # instance to each form that needs it (otherwise they might overwrite
        # each other).
        latest_version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        if not latest_version:
            # No listed version ? Then nothing to do in the listed submission
            # flow.
            return redirect('devhub.submit.finish', addon.slug)

    forms_list = []
    context = {
        'addon': addon,
        'version': version,
        'submit_page': 'version' if version else 'addon',
    }
    post_data = request.POST if request.method == 'POST' else None
    show_all_fields = not version or not addon.has_complete_metadata()

    if show_all_fields:
        describe_form = forms.DescribeForm(
            post_data, instance=addon, request=request)
        cat_form_class = (addon_forms.CategoryFormSet if not static_theme
                          else forms.SingleCategoryForm)
        cat_form = cat_form_class(post_data, addon=addon, request=request)
        license_form = forms.LicenseForm(
            post_data, version=latest_version, prefix='license')
        context.update(license_form.get_context())
        context.update(form=describe_form, cat_form=cat_form)
        forms_list.extend([describe_form, cat_form, context['license_form']])
    if not static_theme:
        # Static themes don't need this form
        reviewer_form = forms.VersionForm(
            post_data, instance=latest_version, request=request)
        context.update(reviewer_form=reviewer_form)
        forms_list.append(reviewer_form)

    if request.method == 'POST' and all(
            form.is_valid() for form in forms_list):
        if show_all_fields:
            addon = describe_form.save()
            cat_form.save()
            license_form.save(log=False)
            if not static_theme:
                reviewer_form.save()
            if addon.status == amo.STATUS_NULL:
                addon.update(status=amo.STATUS_NOMINATED)
            signals.submission_done.send(sender=addon)
        elif not static_theme:
            reviewer_form.save()

        if not version:
            return redirect('devhub.submit.finish', addon.slug)
        else:
            return redirect('devhub.submit.version.finish',
                            addon.slug, version.id)
    template = 'devhub/addons/submit/%s' % (
        'describe.html' if show_all_fields else 'describe_minimal.html')
    return render(request, template, context)


@dev_required(submitting=True)
def submit_addon_details(request, addon_id, addon):
    return _submit_details(request, addon, None)


@dev_required(submitting=True)
def submit_version_details(request, addon_id, addon, version_id):
    version = get_object_or_404(Version, id=version_id)
    return _submit_details(request, addon, version)


def _submit_finish(request, addon, version, is_file=False):
    uploaded_version = version or addon.versions.latest()

    try:
        author = addon.authors.all()[0]
    except IndexError:
        # This should never happen.
        author = None

    if (not version and author and
            uploaded_version.channel == amo.RELEASE_CHANNEL_LISTED and
            not Version.objects.exclude(pk=uploaded_version.pk)
                               .filter(addon__authors=author,
                                       channel=amo.RELEASE_CHANNEL_LISTED)
                               .exclude(addon__status=amo.STATUS_NULL)
                               .exists()):
        # If that's the first time this developer has submitted an listed addon
        # (no other listed Version by this author exists) send them a welcome
        # email.
        # We can use locale-prefixed URLs because the submitter probably
        # speaks the same language by the time he/she reads the email.
        context = {
            'addon_name': unicode(addon.name),
            'app': unicode(request.APP.pretty),
            'detail_url': absolutify(addon.get_url_path()),
            'version_url': absolutify(addon.get_dev_url('versions')),
            'edit_url': absolutify(addon.get_dev_url('edit')),
        }
        tasks.send_welcome_email.delay(addon.id, [author.email], context)

    submit_page = 'file' if is_file else 'version' if version else 'addon'
    return render(request, 'devhub/addons/submit/done.html',
                  {'addon': addon,
                   'uploaded_version': uploaded_version,
                   'submit_page': submit_page})


@dev_required(submitting=True)
def submit_addon_finish(request, addon_id, addon):
    # Bounce to the details step if incomplete
    if (not addon.has_complete_metadata() and
            addon.find_latest_version(channel=amo.RELEASE_CHANNEL_LISTED)):
        return redirect('devhub.submit.details', addon.slug)
    # Bounce to the versions page if they don't have any versions.
    if not addon.versions.exists():
        return redirect('devhub.submit.version', addon.slug)
    return _submit_finish(request, addon, None)


@dev_required
def submit_version_finish(request, addon_id, addon, version_id):
    version = get_object_or_404(Version, id=version_id)
    return _submit_finish(request, addon, version)


@dev_required
def submit_file_finish(request, addon_id, addon, version_id):
    version = get_object_or_404(Version, id=version_id)
    return _submit_finish(request, addon, version, is_file=True)


@login_required
def submit_theme(request):
    if waffle.switch_is_active('disable-lwt-uploads'):
        return redirect('devhub.submit.agreement')
    else:
        return submit_lwt_theme(request)


def submit_lwt_theme(request):
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
            messages.error(
                request,
                ugettext('Please check the form for errors.'))
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


@dev_required
@post_required
def request_review(request, addon_id, addon):
    if not addon.can_request_review():
        return http.HttpResponseBadRequest()

    latest_version = addon.find_latest_version(amo.RELEASE_CHANNEL_LISTED,
                                               exclude=())
    if latest_version:
        for f in latest_version.files.filter(status=amo.STATUS_DISABLED):
            f.update(status=amo.STATUS_AWAITING_REVIEW)
        # Clear the nomination date so it gets set again in Addon.watch_status.
        latest_version.update(nomination=None)
    if addon.has_complete_metadata():
        addon.update(status=amo.STATUS_NOMINATED)
        messages.success(request, ugettext('Review requested.'))
    else:
        messages.success(request, _(
            'You must provide further details to proceed.'))
    ActivityLog.create(amo.LOG.CHANGE_STATUS, addon, addon.status)
    return redirect(addon.get_dev_url('versions'))


@post_required
@addon_view
def admin(request, addon):
    if not acl.action_allowed(request, amo.permissions.ADDONS_CONFIGURE):
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
        'policies': '/AMO/Policy',
        'policies/reviews': '/AMO/Policy/Reviews',
        'policies/contact': '/AMO/Policy/Contact',
        'policies/agreement': '/AMO/Policy/Agreement',
    }

    if doc_name in mdn_docs:
        return redirect(MDN_BASE + mdn_docs[doc_name],
                        permanent=True)

    raise http.Http404()


@login_required
def api_key_agreement(request):
    next_step = reverse('devhub.api_key')
    return render_agreement(request, 'devhub/api/agreement.html', next_step)


def render_agreement(request, template, next_step, **extra_context):
    form = AgreementForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        # Developer has validated the form: let's update its profile and
        # redirect to next step.
        request.user.update(read_dev_agreement=datetime.datetime.now())
        return redirect(next_step)
    elif not request.user.has_read_developer_agreement():
        # Developer has either posted an invalid form or just landed on the
        # page but haven't read the agreement yet: show the form (with
        # potential errors highlighted)
        context = {
            'agreement_form': form,
        }
        context.update(extra_context)
        return render(request, template, context)
    else:
        # The developer has already read the agreement, we should just redirect
        # to the next step.
        response = redirect(next_step)
        return response


@login_required
@transaction.atomic
def api_key(request):
    if not request.user.has_read_developer_agreement():
        return redirect(reverse('devhub.api_key_agreement'))

    try:
        credentials = APIKey.get_jwt_key(user=request.user)
    except APIKey.DoesNotExist:
        credentials = None

    if request.method == 'POST' and request.POST.get('action') == 'generate':
        if credentials:
            log.info('JWT key was made inactive: {}'.format(credentials))
            credentials.update(is_active=None)
            msg = _(
                'Your old credentials were revoked and are no longer valid. '
                'Be sure to update all API clients with the new credentials.')
            messages.success(request, msg)

        new_credentials = APIKey.new_jwt_credentials(request.user)
        log.info('new JWT key created: {}'.format(new_credentials))

        send_key_change_email(request.user.email, new_credentials.key)

        return redirect(reverse('devhub.api_key'))

    if request.method == 'POST' and request.POST.get('action') == 'revoke':
        credentials.update(is_active=None)
        log.info('revoking JWT key for user: {}, {}'
                 .format(request.user.id, credentials))
        send_key_revoked_email(request.user.email, credentials.key)
        msg = ugettext(
            'Your old credentials were revoked and are no longer valid.')
        messages.success(request, msg)
        return redirect(reverse('devhub.api_key'))

    return render(request, 'devhub/api/key.html',
                  {'title': ugettext('Manage API Keys'),
                   'credentials': credentials})


def send_key_change_email(to_email, key):
    template = loader.get_template('devhub/email/new-key-email.ltxt')
    url = absolutify(reverse('devhub.api_key'))
    send_mail(
        ugettext('New API key created'),
        template.render({'key': key, 'url': url}),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[to_email],
    )


def send_key_revoked_email(to_email, key):
    template = loader.get_template('devhub/email/revoked-key-email.ltxt')
    url = absolutify(reverse('devhub.api_key'))
    send_mail(
        ugettext('API key revoked'),
        template.render({'key': key, 'url': url}),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[to_email],
    )
