import collections
import datetime
import functools
import json
import os
import time
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
from django.utils.translation import ugettext as _, ugettext_lazy as _lazy
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

import commonware.log
import waffle
from django_statsd.clients import statsd
from PIL import Image

from olympia import amo
from olympia.amo import utils as amo_utils
from olympia.access import acl
from olympia.addons import forms as addon_forms
from olympia.addons.decorators import addon_view
from olympia.addons.models import Addon, AddonUser
from olympia.addons.views import BaseFilter
from olympia.amo import messages
from olympia.amo.decorators import json_view, login_required, post_required
from olympia.amo.helpers import absolutify, urlparams
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import escape_all, MenuItem, send_mail
from olympia.api.models import APIKey
from olympia.applications.models import AppVersion
from olympia.devhub.decorators import dev_required
from olympia.devhub.forms import CheckCompatibilityForm
from olympia.devhub.models import ActivityLog, BlogPost, RssKey, SubmitStep
from olympia.devhub.utils import (
    ValidationAnnotator, ValidationComparator, process_validation)
from olympia.editors.decorators import addons_reviewer_required
from olympia.editors.helpers import get_position, ReviewHelper
from olympia.files.models import (
    File, FileUpload, FileValidation, ValidationAnnotation)
from olympia.files.utils import is_beta, parse_addon
from olympia.lib.crypto.packaged import sign_file
from olympia.search.views import BaseAjaxSearch
from olympia.translations.models import delete_translation
from olympia.users.models import UserProfile
from olympia.versions.models import Version
from olympia.zadmin.models import ValidationResult

from . import forms, tasks, feeds, signals


log = commonware.log.getLogger('z.devhub')
paypal_log = commonware.log.getLogger('z.paypal')


# We use a session cookie to make sure people see the dev agreement.

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
        qs = request.user.addons.filter(type=amo.ADDON_PERSONA)
    else:
        qs = Addon.with_unlisted.filter(authors=request.user).exclude(
            type=amo.ADDON_PERSONA)
    filter_cls = ThemeFilter if theme else AddonFilter
    filter_ = filter_cls(request, qs, 'sort', default)
    return filter_.qs, filter_


def index(request):

    ctx = {'blog_posts': _get_posts()}
    if request.user.is_authenticated():
        user_addons = Addon.with_unlisted.filter(authors=request.user)
        recent_addons = user_addons.order_by('-modified')[:3]
        ctx['recent_addons'] = []
        for addon in recent_addons:
            ctx['recent_addons'].append({'addon': addon,
                                         'position': get_position(addon)})

    return render(request, 'devhub/index.html', ctx)


@login_required
def dashboard(request, theme=False):
    addon_items = _get_items(
        None, Addon.with_unlisted.filter(authors=request.user))[:4]

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
    version = get_object_or_404(Version, pk=version_id, addon=addon)
    compat_form = forms.CompatFormSet(request.POST or None,
                                      queryset=version.apps.all())
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
        url = reverse('users.login')
        p = urlquote(request.get_full_path())
        return http.HttpResponseRedirect('%s?to=%s' % (url, p))
    else:
        addons_all = Addon.with_unlisted.filter(authors=request.user)

        if addon_id:
            addon = get_object_or_404(Addon.with_unlisted.id_or_slug(addon_id))
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

    pager = amo_utils.paginate(request, items, 20)
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

    form = forms.DeleteForm(request.POST, addon=addon)
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
                _('URL name was incorrect. Theme was not deleted.'))
            return redirect(addon.get_dev_url())
        else:
            messages.error(
                request,
                _('URL name was incorrect. Add-on was not deleted.'))
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
    if addon.latest_version:
        addon.latest_version.files.filter(
            status=amo.STATUS_UNREVIEWED).update(status=amo.STATUS_DISABLED)
    addon.update_version()
    amo.log(amo.LOG.USER_DISABLE, addon)
    return redirect(addon.get_dev_url('versions'))


@dev_required
@post_required
def unlist(request, addon_id, addon):
    addon.update(is_listed=False, disabled_by_user=False)
    amo.log(amo.LOG.ADDON_UNLISTED, addon)
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
        from olympia.amo.utils import send_mail

        t = loader.get_template(
            'users/email/{part}.ltxt'.format(part=template_part))
        send_mail(title,
                  t.render(Context({'author': author, 'addon': addon,
                                    'site_url': settings.SITE_URL})),
                  None, recipients, use_blacklist=False)

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
            author.delete()
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
                   # Hack: we just need the "is_unlisted" field from this form.
                   'new_addon_form': forms.NewAddonForm(
                       None, None, request=request)})


@login_required
def check_addon_compatibility(request):
    form = CheckCompatibilityForm()
    return render(request, 'devhub/validate_addon.html',
                  {'appversion_form': form,
                   'title': _('Check Add-on Compatibility'),
                   # Hack: we just need the "is_unlisted" field from this form.
                   'new_addon_form': forms.NewAddonForm(
                       None, None, request=request)})


def handle_upload(filedata, user, app_id=None, version_id=None, addon=None,
                  is_standalone=False, is_listed=True, automated=False,
                  submit=False):
    if addon:
        # TODO: Handle betas.
        automated = addon.automated_signing
        is_listed = addon.is_listed

    upload = FileUpload.from_post(filedata, filedata.name, filedata.size,
                                  automated_signing=automated, addon=addon)
    log.info('FileUpload created: %s' % upload.uuid)
    if user.is_authenticated():
        upload.user = user
        upload.save()
    if app_id and version_id:
        app = amo.APPS_ALL.get(int(app_id))
        if not app:
            raise http.Http404()
        ver = get_object_or_404(AppVersion, pk=version_id)
        tasks.compatibility_check.delay(upload.pk, app.guid, ver.version)
    elif submit:
        tasks.validate_and_submit(addon, upload, listed=is_listed)
    else:
        tasks.validate(upload, listed=is_listed)

    return upload


@login_required
@post_required
def upload(request, addon=None, is_standalone=False, is_listed=True,
           automated=False):
    filedata = request.FILES['upload']
    app_id = request.POST.get('app_id')
    version_id = request.POST.get('version_id')
    upload = handle_upload(
        filedata=filedata, user=request.user, app_id=app_id,
        version_id=version_id, addon=addon, is_standalone=is_standalone,
        is_listed=is_listed, automated=automated)
    if addon:
        return redirect('devhub.upload_detail_for_addon',
                        addon.slug, upload.uuid)
    elif is_standalone:
        return redirect('devhub.standalone_upload_detail', upload.uuid)
    else:
        return redirect('devhub.upload_detail', upload.uuid, 'json')


@post_required
@dev_required
def upload_for_addon(request, addon_id, addon):
    return upload(request, addon=addon)


@login_required
@json_view
def standalone_upload_detail(request, uuid):
    upload = get_object_or_404(FileUpload, uuid=uuid)
    url = reverse('devhub.standalone_upload_detail', args=[uuid])
    return upload_validation_context(request, upload, url=url)


@dev_required
@json_view
def upload_detail_for_addon(request, addon_id, addon, uuid):
    try:
        upload = get_object_or_404(FileUpload, uuid=uuid)
        response = json_upload_detail(request, upload, addon_slug=addon.slug)
        statsd.incr('devhub.upload_detail_for_addon.success')
        return response
    except Exception as exc:
        statsd.incr('devhub.upload_detail_for_addon.error')
        log.error('Error checking upload status: {} {}'.format(type(exc), exc))
        raise


@dev_required(allow_editors=True)
def file_validation(request, addon_id, addon, file_id):
    file_ = get_object_or_404(File, id=file_id)

    validate_url = reverse('devhub.json_file_validation',
                           args=[addon.slug, file_.id])

    prev_file = ValidationAnnotator(file_).prev_file
    if prev_file:
        file_url = reverse('files.compare', args=[file_.id, prev_file.id,
                                                  'file', ''])
    else:
        file_url = reverse('files.list', args=[file_.id, 'file', ''])

    context = {'validate_url': validate_url, 'file_url': file_url,
               'file': file_, 'filename': file_.filename,
               'timestamp': file_.created, 'addon': addon,
               'automated_signing': file_.automated_signing}

    if acl.check_addons_reviewer(request):
        context['annotate_url'] = reverse('devhub.annotate_file_validation',
                                          args=[addon.slug, file_id])

    if file_.has_been_validated:
        context['validation_data'] = file_.validation.processed_validation

    return render(request, 'devhub/validation.html', context)


@post_required
@addons_reviewer_required
@json_view
def annotate_file_validation(request, addon_id, file_id):
    file_ = get_object_or_404(File, pk=file_id)

    form = forms.AnnotateFileForm(request.POST)
    if not form.is_valid():
        return {'status': 'fail',
                'errors': dict(form.errors.items())}

    message_key = ValidationComparator.message_key(
        form.cleaned_data['message'])

    updates = {'ignore_duplicates': form.cleaned_data['ignore_duplicates']}

    annotation, created = ValidationAnnotation.objects.get_or_create(
        file_hash=file_.original_hash, message_key=json.dumps(message_key),
        defaults=updates)

    if not created:
        annotation.update(**updates)

    return {'status': 'ok'}


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
    try:
        v_result = file.validation
    except FileValidation.DoesNotExist:
        if request.method != 'POST':
            return http.HttpResponseNotAllowed(['POST'])

        # This API is, unfortunately, synchronous, so wait for the
        # task to complete and return the result directly.
        v_result = tasks.validate(file).get()

    return {'validation': v_result.processed_validation, 'error': None}


@json_view
@csrf_exempt
@post_required
@dev_required(allow_editors=True)
def json_bulk_compat_result(request, addon_id, addon, result_id):
    result = get_object_or_404(ValidationResult, pk=result_id,
                               completed__isnull=False)

    validation = json.loads(result.validation)
    return {'validation': process_validation(validation), 'error': None}


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
            if not acl.submission_allowed(request.user, pkg):
                raise django_forms.ValidationError(
                    _(u'You cannot submit this type of add-on'))
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

    if not url:
        if addon:
            url = reverse('devhub.upload_detail_for_addon',
                          args=[addon.slug, upload.uuid])
        else:
            url = reverse('devhub.upload_detail', args=[upload.uuid, 'json'])
    full_report_url = reverse('devhub.upload_detail', args=[upload.uuid])

    validation = upload.processed_validation or ''

    processed_by_linter = (
        validation and
        validation.get('metadata', {}).get(
            'processed_by_addons_linter', False))

    return {'upload': upload.uuid,
            'validation': validation,
            'error': None,
            'url': url,
            'full_report_url': full_report_url,
            'processed_by_addons_linter': processed_by_linter}


@login_required
def upload_detail(request, uuid, format='html'):
    if format == 'json' or request.is_ajax():
        try:
            # This is duplicated in the HTML code path.
            upload = get_object_or_404(FileUpload, uuid=uuid)
            response = json_upload_detail(request, upload)
            statsd.incr('devhub.upload_detail.success')
            return response
        except Exception as exc:
            statsd.incr('devhub.upload_detail.error')
            log.error('Error checking upload status: {} {}'.format(
                type(exc), exc))
            raise

    # This is duplicated in the JSON code path.
    upload = get_object_or_404(FileUpload, uuid=uuid)

    validate_url = reverse('devhub.standalone_upload_detail',
                           args=[upload.uuid])

    if upload.compat_with_app:
        return _compat_result(request, validate_url,
                              upload.compat_with_app,
                              upload.compat_with_appver)

    context = {'validate_url': validate_url, 'filename': upload.name,
               'automated_signing': upload.automated_signing,
               'timestamp': upload.created}

    if upload.validation:
        context['validation_data'] = upload.processed_validation

    return render(request, 'devhub/validation.html', context)


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

        check = amo_utils.ImageCheck(upload_preview)
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

            for compat in data['compat_form'].deleted_objects:
                compat.delete()

            for form in data['compat_form'].forms:
                if (isinstance(form, forms.CompatForm) and
                        'max' in form.changed_data):
                    _log_max_version_change(addon, version, form.instance)

        fields = ('source', 'approvalnotes')
        has_changed = [field in version_form.changed_data for field in fields]
        if version.has_info_request and any(has_changed):
            version.update(has_info_request=False)
            version.save()
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
@transaction.atomic
def version_delete(request, addon_id, addon):
    version_id = request.POST.get('version_id')
    version = get_object_or_404(Version, pk=version_id, addon=addon)
    if 'disable_version' in request.POST:
        messages.success(request, _('Version %s disabled.') % version.version)
        version.is_user_disabled = True
        version.addon.update_status()
    else:
        messages.success(request, _('Version %s deleted.') % version.version)
        version.delete()
    return redirect(addon.get_dev_url('versions'))


@dev_required
@post_required
@transaction.atomic
def version_reenable(request, addon_id, addon):
    version_id = request.POST.get('version_id')
    version = get_object_or_404(Version, pk=version_id, addon=addon)
    messages.success(request, _('Version %s re-enabled.') % version.version)
    version.is_user_disabled = False
    version.addon.update_status()
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


def auto_sign_file(file_, is_beta=False):
    """If the file should be automatically reviewed and signed, do it."""
    addon = file_.version.addon
    validation = file_.validation

    if file_.is_experiment:  # See bug 1220097.
        amo.log(amo.LOG.EXPERIMENT_SIGNED, file_)
        sign_file(file_, settings.PRELIMINARY_SIGNING_SERVER)
    elif is_beta:
        # Beta won't be reviewed. They will always get signed, and logged, for
        # further review if needed.
        if validation.passed_auto_validation:
            amo.log(amo.LOG.BETA_SIGNED_VALIDATION_PASSED, file_)
        else:
            amo.log(amo.LOG.BETA_SIGNED_VALIDATION_FAILED, file_)
        # Beta files always get signed with prelim cert.
        sign_file(file_, settings.PRELIMINARY_SIGNING_SERVER)
    elif addon.automated_signing:
        # Sign automatically without manual review.
        helper = ReviewHelper(request=None, addon=addon,
                              version=file_.version)
        # Provide the file to review/sign to the helper.
        helper.set_data({'addon_files': [file_],
                         'comments': 'automatic validation'})
        if addon.is_sideload:
            helper.handler.process_public(auto_validation=True)
            if validation.passed_auto_validation:
                amo.log(amo.LOG.UNLISTED_SIDELOAD_SIGNED_VALIDATION_PASSED,
                        file_)
            else:
                amo.log(amo.LOG.UNLISTED_SIDELOAD_SIGNED_VALIDATION_FAILED,
                        file_)
        else:
            helper.handler.process_preliminary(auto_validation=True)
            if validation.passed_auto_validation:
                amo.log(amo.LOG.UNLISTED_SIGNED_VALIDATION_PASSED, file_)
            else:
                amo.log(amo.LOG.UNLISTED_SIGNED_VALIDATION_FAILED, file_)


def auto_sign_version(version, **kwargs):
    # Sign all the files submitted, one for each platform.
    for file_ in version.files.all():
        auto_sign_file(file_, **kwargs)


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
    if not form.is_valid():
        return json_view.error(form.errors)

    is_beta = form.cleaned_data['beta'] and addon.is_listed
    pl = form.cleaned_data.get('supported_platforms', [])
    version = Version.from_upload(
        upload=form.cleaned_data['upload'],
        addon=addon,
        platforms=pl,
        source=form.cleaned_data['source'],
        is_beta=is_beta
    )
    rejected_versions = addon.versions.filter(
        version=version.version, files__status=amo.STATUS_DISABLED)[:1]
    if not version.releasenotes and rejected_versions:
        # Let's reuse the release and approval notes from the previous
        # rejected version.
        last_rejected = rejected_versions[0]
        version.releasenotes = amo_utils.translations_for_field(
            last_rejected.releasenotes)
        version.approvalnotes = last_rejected.approvalnotes
        version.save()
    log.info('Version created: %s for: %s' %
             (version.pk, form.cleaned_data['upload']))
    check_validation_override(request, form, addon, version)
    if (addon.status == amo.STATUS_NULL and
            form.cleaned_data['nomination_type']):
        addon.update(status=form.cleaned_data['nomination_type'])
    url = reverse('devhub.versions.edit',
                  args=[addon.slug, str(version.id)])

    # Sign all the files submitted, one for each platform.
    auto_sign_version(version, is_beta=is_beta)

    return dict(url=url)


@json_view
@dev_required
@post_required
def version_add_file(request, addon_id, addon, version_id):
    version = get_object_or_404(Version, pk=version_id, addon=addon)
    new_file_form = forms.NewFileForm(request.POST, request.FILES, addon=addon,
                                      version=version, request=request)
    if not new_file_form.is_valid():
        return json_view.error(new_file_form.errors)
    upload = new_file_form.cleaned_data['upload']
    is_beta = new_file_form.cleaned_data['beta'] and addon.is_listed
    new_file = File.from_upload(upload, version,
                                new_file_form.cleaned_data['platform'],
                                is_beta, parse_addon(upload, addon))
    source = new_file_form.cleaned_data['source']
    if source:
        version.update(source=source)
    storage.delete(upload.path)
    check_validation_override(request, new_file_form, addon, new_file.version)
    file_form = forms.FileFormSet(prefix='files', queryset=version.files.all())
    form = [f for f in file_form.forms if f.instance == new_file]

    auto_sign_file(new_file, is_beta=is_beta)

    return render(request, 'devhub/includes/version_file.html',
                  {'form': form[0], 'addon': addon})


@dev_required
def version_list(request, addon_id, addon):
    qs = addon.versions.order_by('-created').transform(Version.transformer)
    versions = amo_utils.paginate(request, qs)
    new_file_form = forms.NewVersionForm(None, addon=addon, request=request)
    is_admin = acl.action_allowed(request, 'ReviewerAdminTools', 'View')

    data = {'addon': addon,
            'versions': versions,
            'new_file_form': new_file_form,
            'position': get_position(addon),
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
    return render_agreement(request, 'devhub/addons/submit/start.html',
                            _step_url(2), step)


@login_required
@submit_step(2)
@transaction.atomic
def submit_addon(request, step):
    if request.user.read_dev_agreement is None:
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

            is_listed = not data['is_unlisted']

            addon = Addon.from_upload(data['upload'], p, source=data['source'],
                                      is_listed=is_listed)
            AddonUser(addon=addon, user=request.user).save()
            check_validation_override(request, form, addon,
                                      addon.current_version)
            if not addon.is_listed:  # Not listed? Automatically choose queue.
                if data.get('is_sideload'):  # Full review needed.
                    addon.update(status=amo.STATUS_NOMINATED)
                else:  # Otherwise, simply do a prelim review.
                    addon.update(status=amo.STATUS_UNREVIEWED)
                # Sign all the files submitted, one for each platform.
                auto_sign_version(addon.versions.get())
            SubmitStep.objects.create(addon=addon, step=3)
            return redirect(_step_url(3), addon.slug)
    is_admin = acl.action_allowed(request, 'ReviewerAdminTools', 'View')

    return render(request, 'devhub/addons/submit/upload.html',
                  {'step': step, 'new_addon_form': form, 'is_admin': is_admin})


@dev_required
@submit_step(3)
def submit_describe(request, addon_id, addon, step):
    form_cls = forms.Step3Form
    form = form_cls(request.POST or None, instance=addon, request=request)
    cat_form = addon_forms.CategoryFormSet(request.POST or None, addon=addon,
                                           request=request)

    if request.method == 'POST' and form.is_valid() and (
            not addon.is_listed or cat_form.is_valid()):
        addon = form.save(addon)
        submit_step = SubmitStep.objects.filter(addon=addon)
        if addon.is_listed:
            cat_form.save()
            submit_step.update(step=4)
            return redirect(_step_url(4), addon.slug)
        else:  # Finished for unlisted addons.
            submit_step.delete()
            signals.submission_done.send(sender=addon)
            return redirect('devhub.submit.7', addon.slug)
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
                'policies/agreement',
                'policies/contact')

    if doc_name in mdn_docs:
        return redirect(MDN_BASE + mdn_docs[doc_name],
                        permanent=True)

    if doc_name in all_docs:
        filename = '%s.html' % doc_name.replace('/', '-')
        return render(request, 'devhub/docs/%s' % filename)

    raise http.Http404()


@login_required
def api_key_agreement(request):
    next_step = reverse('devhub.api_key')
    return render_agreement(request, 'devhub/api/agreement.html', next_step)


def render_agreement(request, template, next_step, step=None):
    if request.method == 'POST':
        request.user.update(read_dev_agreement=datetime.datetime.now())
        return redirect(next_step)

    if request.user.read_dev_agreement is None:
        return render(request, template,
                      {'step': step})
    else:
        response = redirect(next_step)
        return response


@login_required
@transaction.atomic
def api_key(request):
    if request.user.read_dev_agreement is None:
        return redirect(reverse('devhub.api_key_agreement'))

    try:
        credentials = APIKey.get_jwt_key(user=request.user)
    except APIKey.DoesNotExist:
        credentials = None

    if request.method == 'POST' and request.POST.get('action') == 'generate':
        if credentials:
            log.info('JWT key was made inactive: {}'.format(credentials))
            credentials.update(is_active=False)
            msg = _(
                'Your old credentials were revoked and are no longer valid. '
                'Be sure to update all API clients with the new credentials.')
            messages.success(request, msg)

        new_credentials = APIKey.new_jwt_credentials(request.user)
        log.info('new JWT key created: {}'.format(new_credentials))

        send_key_change_email(request.user.email, new_credentials.key)

        return redirect(reverse('devhub.api_key'))

    if request.method == 'POST' and request.POST.get('action') == 'revoke':
        credentials.update(is_active=False)
        log.info('revoking JWT key for user: {}, {}'
                 .format(request.user.id, credentials))
        send_key_revoked_email(request.user.email, credentials.key)
        msg = _('Your old credentials were revoked and are no longer valid.')
        messages.success(request, msg)
        return redirect(reverse('devhub.api_key'))

    return render(request, 'devhub/api/key.html',
                  {'title': _('Manage API Keys'),
                   'credentials': credentials})


def send_key_change_email(to_email, key):
    template = loader.get_template('devhub/email/new-key-email.ltxt')
    url = absolutify(reverse('devhub.api_key'))
    send_mail(
        _('New API key created'),
        template.render(Context({'key': key, 'url': url})),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[to_email],
    )


def send_key_revoked_email(to_email, key):
    template = loader.get_template('devhub/email/revoked-key-email.ltxt')
    url = absolutify(reverse('devhub.api_key'))
    send_mail(
        _('API key revoked'),
        template.render(Context({'key': key, 'url': url})),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[to_email],
    )
