import datetime
import os
import time

from uuid import UUID, uuid4

from django import forms as django_forms, http
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage as storage
from django.db import transaction
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template import loader
from django.utils.translation import ugettext, ugettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

import waffle

from csp.decorators import csp_update
from django_statsd.clients import statsd

import olympia.core.logger

from olympia import amo
from olympia.access import acl
from olympia.accounts.utils import redirect_for_login, _is_safe_url
from olympia.accounts.views import API_TOKEN_COOKIE, logout_user
from olympia.activity.models import ActivityLog, VersionLog
from olympia.activity.utils import log_and_notify
from olympia.addons.models import (
    Addon, AddonReviewerFlags, AddonUser, AddonUserPendingConfirmation)
from olympia.addons.views import BaseFilter
from olympia.amo import messages, utils as amo_utils
from olympia.amo.decorators import json_view, login_required, post_required
from olympia.amo.templatetags.jinja_helpers import absolutify, urlparams
from olympia.amo.urlresolvers import get_url_prefix, reverse
from olympia.amo.utils import MenuItem, escape_all, render, send_mail
from olympia.api.models import APIKey, APIKeyConfirmation
from olympia.devhub.decorators import dev_required, no_admin_disabled
from olympia.devhub.models import BlogPost, RssKey
from olympia.devhub.utils import (
    add_dynamic_theme_tag, extract_theme_properties,
    UploadRestrictionChecker, wizard_unsupported_properties)
from olympia.files.models import File, FileUpload
from olympia.files.utils import parse_addon
from olympia.reviewers.forms import PublicWhiteboardForm
from olympia.reviewers.models import Whiteboard
from olympia.reviewers.templatetags.jinja_helpers import get_position
from olympia.reviewers.utils import ReviewHelper
from olympia.users.models import DeveloperAgreementRestriction
from olympia.versions.models import Version
from olympia.versions.tasks import extract_version_source_to_git
from olympia.versions.utils import get_next_version_number
from olympia.zadmin.models import get_config

from . import feeds, forms, signals, tasks


log = olympia.core.logger.getLogger('z.devhub')


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
        qs = Addon.objects.filter(
            authors=request.user, type=amo.ADDON_STATICTHEME)
        filter_cls = ThemeFilter
        default = 'created'
    else:
        qs = Addon.objects.filter(authors=request.user).exclude(
            type=amo.ADDON_STATICTHEME)
        filter_cls = AddonFilter
        default = 'updated'
    filter_ = filter_cls(request, qs, 'sort', default)
    return filter_.qs, filter_


@csp_update(CONNECT_SRC=settings.MOZILLA_NEWLETTER_URL,
            FORM_ACTION=settings.MOZILLA_NEWLETTER_URL)
def index(request):
    ctx = {}
    if request.user.is_authenticated:
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
    version = get_object_or_404(addon.versions.all(), pk=version_id)
    compat_form = forms.CompatFormSet(
        request.POST or None,
        queryset=version.apps.all().select_related('min', 'max'),
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
    key, _ = RssKey.objects.get_or_create(user=request.user)
    return urlparams(reverse('devhub.feed_all'), privaterss=key.key.hex)


def feed(request, addon_id=None):
    if request.GET.get('privaterss'):
        return feeds.ActivityFeedRSS()(request)

    addon_selected = None

    if not request.user.is_authenticated:
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
                               privaterss=key.key.hex)

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

    previews = (
        addon.current_version.previews.all()
        if addon.current_version and addon.has_per_version_previews
        else addon.previews.all())
    header_preview = (
        previews.first() if addon.type == amo.ADDON_STATICTHEME else None)
    data = {
        'page': 'edit',
        'addon': addon,
        'whiteboard': whiteboard,
        'editable': False,
        'show_listed_fields': addon.has_listed_versions(),
        'valid_slug': addon.slug,
        'tags': addon.tags.not_denied().values_list('tag_text', flat=True),
        'previews': previews,
        'header_preview': header_preview,
        'supported_image_types': amo.SUPPORTED_IMAGE_TYPES,
    }

    return render(request, 'devhub/addons/edit.html', data)


@dev_required(owner_for_post=True)
@post_required
def delete(request, addon_id, addon):
    # Database deletes only allowed for free or incomplete addons.
    if not addon.can_be_deleted():
        msg = ugettext(
            'Add-on cannot be deleted. Disable this add-on instead.')
        messages.error(request, msg)
        return redirect(addon.get_dev_url('versions'))

    any_theme = addon.type == amo.ADDON_STATICTHEME
    form = forms.DeleteForm(request.POST, addon=addon)
    if form.is_valid():
        reason = form.cleaned_data.get('reason', '')
        addon.delete(msg='Removed via devhub', reason=reason)
        messages.success(
            request,
            ugettext('Theme deleted.')
            if any_theme else ugettext('Add-on deleted.'))
        return redirect('devhub.%s' % ('themes' if any_theme else 'addons'))
    else:
        messages.error(
            request,
            ugettext('URL name was incorrect. Theme was not deleted.')
            if any_theme else
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


# Can't use @dev_required, as the user is not a developer yet. Can't use
# @addon_view_factory either, because it requires a developer for unlisted
# add-ons. So we just @login_required and retrieve the addon ourselves in the
# function.
@login_required
def invitation(request, addon_id):
    addon = get_object_or_404(Addon.objects.id_or_slug(addon_id))
    try:
        invitation = AddonUserPendingConfirmation.objects.get(
            addon=addon, user=request.user)
    except AddonUserPendingConfirmation.DoesNotExist:
        # To be nice in case the user accidentally visited this page after
        # having accepted an invite, redirect to the add-on base edit page.
        # If they are an author, they will have access, otherwise will get the
        # appropriate error.
        return redirect(addon.get_dev_url())
    if request.method == 'POST':
        value = request.POST.get('accept')
        if value == 'yes':
            # There is a potential race condition on the position, but it's
            # difficult to find a sensible value anyway. Should a position
            # conflict happen, owners can easily fix it themselves.
            last_position = AddonUser.objects.filter(
                addon=invitation.addon).order_by('position').values_list(
                'position', flat=True).last() or 0
            AddonUser.objects.create(
                addon=invitation.addon, user=invitation.user,
                role=invitation.role, listed=invitation.listed,
                position=last_position + 1)
            messages.success(request, ugettext('Invitation accepted.'))
            redirect_url = addon.get_dev_url()
        else:
            messages.success(request, ugettext('Invitation declined.'))
            redirect_url = reverse('devhub.addons')
        # Regardless of whether or not the invitation was accepted or not,
        # it's now obsolete.
        invitation.delete()
        return redirect(redirect_url)
    ctx = {
        'addon': addon,
        'invitation': invitation,
    }
    return render(request, 'devhub/addons/invitation.html', ctx)


@dev_required(owner_for_post=True)
def ownership(request, addon_id, addon):
    fs = []
    ctx = {'addon': addon}
    post_data = request.POST if request.method == 'POST' else None
    # Authors.
    user_form = forms.AuthorFormSet(
        post_data,
        prefix='user_form',
        queryset=AddonUser.objects.filter(addon=addon).order_by('position'),
        form_kwargs={'addon': addon})
    fs.append(user_form)
    ctx['user_form'] = user_form
    # Authors pending confirmation (owner can still remove them before they
    # accept).
    authors_pending_confirmation_form = forms.AuthorWaitingConfirmationFormSet(
        post_data,
        prefix='authors_pending_confirmation',
        queryset=AddonUserPendingConfirmation.objects.filter(
            addon=addon).order_by('id'),
        form_kwargs={'addon': addon})
    fs.append(authors_pending_confirmation_form)
    ctx['authors_pending_confirmation_form'] = (
        authors_pending_confirmation_form)
    # Versions.
    license_form = forms.LicenseForm(post_data, version=addon.current_version)
    ctx.update(license_form.get_context())
    if ctx['license_form']:  # if addon has a version
        fs.append(ctx['license_form'])
    # Policy.
    if addon.type != amo.ADDON_STATICTHEME:
        policy_form = forms.PolicyForm(post_data, addon=addon)
        ctx['policy_form'] = policy_form
        fs.append(policy_form)
    else:
        policy_form = None

    def mail_user_changes(author, title, template_part, recipients,
                          extra_context=None):
        from olympia.amo.utils import send_mail

        context_data = {
            'author': author,
            'addon': addon,
            'DOMAIN': settings.DOMAIN,
        }
        if extra_context:
            context_data.update(extra_context)
        template = loader.get_template(
            'users/email/{part}.ltxt'.format(part=template_part))
        send_mail(title, template.render(context_data),
                  None, recipients, use_deny_list=False)

    def process_author_changes(source_form, existing_authors_emails):
        addon_users_to_process = source_form.save(commit=False)
        for addon_user in addon_users_to_process:
            action = None
            addon_user.addon = addon
            if not addon_user.pk:
                action = amo.LOG.ADD_USER_WITH_ROLE
                mail_user_changes(
                    author=addon_user,
                    title=ugettext('An author has been added to your add-on'),
                    template_part='author_added',
                    recipients=existing_authors_emails)
                mail_user_changes(
                    author=addon_user,
                    title=ugettext(
                        'Author invitation for {addon_name}').format(
                        addon_name=str(addon.name)),
                    template_part='author_added_confirmation',
                    recipients=[addon_user.user.email],
                    extra_context={'author_confirmation_link': absolutify(
                        reverse('devhub.addons.invitation', args=(addon.slug,))
                    )})
                messages.success(request, ugettext(
                    'A confirmation email has been sent to {email}').format(
                    email=addon_user.user.email))

            elif addon_user.role != addon_user._original_role:
                action = amo.LOG.CHANGE_USER_WITH_ROLE
                title = ugettext(
                    'An author role has been changed on your add-on')
                recipients = list(
                    set(existing_authors_emails + [addon_user.user.email])
                )
                mail_user_changes(
                    author=addon_user,
                    title=title,
                    template_part='author_changed',
                    recipients=recipients)
            addon_user.save()
            if action:
                ActivityLog.create(
                    action, addon_user.user,
                    str(addon_user.get_role_display()), addon)
        for addon_user in source_form.deleted_objects:
            recipients = list(
                set(existing_authors_emails + [addon_user.user.email])
            )
            ActivityLog.create(
                amo.LOG.REMOVE_USER_WITH_ROLE, addon_user.user,
                str(addon_user.get_role_display()), addon)
            mail_user_changes(
                author=addon_user,
                title=ugettext('An author has been removed from your add-on'),
                template_part='author_removed',
                recipients=recipients)
            addon_user.delete()

    if request.method == 'POST' and all([form.is_valid() for form in fs]):
        if license_form in fs:
            license_form.save()
        if policy_form and policy_form in fs:
            policy_form.save()
        messages.success(request, ugettext('Changes successfully saved.'))

        existing_authors_emails = list(
            addon.authors.values_list('email', flat=True))

        process_author_changes(
            authors_pending_confirmation_form, existing_authors_emails)
        process_author_changes(
            user_form, existing_authors_emails)

        return redirect(addon.get_dev_url('owner'))

    return render(request, 'devhub/addons/owner.html', ctx)


@login_required
def validate_addon(request):
    return render(request, 'devhub/validate_addon.html',
                  {'title': ugettext('Validate Add-on'),
                   'new_addon_form': forms.DistributionChoiceForm()})


def handle_upload(filedata, request, channel, addon=None, is_standalone=False,
                  submit=False):
    automated_signing = channel == amo.RELEASE_CHANNEL_UNLISTED

    user = request.user if request.user.is_authenticated else None
    upload = FileUpload.from_post(
        filedata, filedata.name, filedata.size,
        automated_signing=automated_signing, addon=addon, user=user)
    log.info('FileUpload created: %s' % upload.uuid.hex)

    if submit:
        tasks.validate_and_submit(
            addon, upload, channel=channel)
    else:
        tasks.validate(
            upload, listed=(channel == amo.RELEASE_CHANNEL_LISTED))

    return upload


@login_required
@post_required
def upload(request, channel='listed', addon=None, is_standalone=False):
    channel = amo.CHANNEL_CHOICES_LOOKUP[channel]
    filedata = request.FILES['upload']
    upload = handle_upload(
        filedata=filedata, request=request, addon=addon,
        is_standalone=is_standalone, channel=channel)
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
    file_ = get_object_or_404(File, version__addon=addon, id=file_id)

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


@csrf_exempt
@dev_required(allow_reviewers=True)
def json_file_validation(request, addon_id, addon, file_id):
    file = get_object_or_404(File, version__addon=addon, id=file_id)
    try:
        result = file.validation
    except File.validation.RelatedObjectDoesNotExist:
        raise http.Http404
    response = JsonResponse({
        'validation': result.processed_validation,
        'error': None,
    })
    # See: https://github.com/mozilla/addons-server/issues/11048
    response['Access-Control-Allow-Origin'] = settings.CODE_MANAGER_URL
    response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response['Access-Control-Allow-Headers'] = 'Content-Type'
    response['Access-Control-Allow-Credentials'] = 'true'
    return response


@json_view
def json_upload_detail(request, upload, addon_slug=None):
    addon = None
    if addon_slug:
        addon = get_object_or_404(Addon.objects, slug=addon_slug)
    result = upload_validation_context(request, upload, addon=addon)
    if result['validation']:
        try:
            pkg = parse_addon(upload, addon=addon, user=request.user)
        except django_forms.ValidationError as exc:
            # Don't add custom validation errors if we already
            # failed validation (This can happen because validation does
            # call `parse_addon` too.)
            if result['validation'].get('errors', 0):
                return result

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
            return json_view.error(result)
        else:
            result['addon_type'] = pkg.get('type', '')
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

    return {'upload': upload.uuid.hex,
            'validation': validation,
            'error': None,
            'url': url,
            'full_report_url': full_report_url}


def upload_detail(request, uuid, format='html'):
    upload = get_fileupload_by_uuid_or_404(uuid)
    if upload.user_id and not request.user.is_authenticated:
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

    context = {'validate_url': validate_url, 'filename': upload.pretty_name,
               'automated_signing': upload.automated_signing,
               'timestamp': upload.created}

    if upload.validation:
        context['validation_data'] = upload.processed_validation

    return render(request, 'devhub/validation.html', context)


@dev_required
def addons_section(request, addon_id, addon, section, editable=False):
    show_listed = addon.has_listed_versions()
    static_theme = addon.type == amo.ADDON_STATICTHEME
    models = {}
    content_waffle = waffle.switch_is_active('content-optimization')
    if show_listed:
        models.update({
            'describe': (forms.DescribeForm if not content_waffle
                         else forms.DescribeFormContentOptimization),
            'additional_details': forms.AdditionalDetailsForm,
            'technical': forms.AddonFormTechnical
        })
        if not static_theme:
            models.update({'media': forms.AddonFormMedia})
    else:
        models.update({
            'describe': (forms.DescribeFormUnlisted if not content_waffle
                         else forms.DescribeFormUnlistedContentOptimization),
            'additional_details': forms.AdditionalDetailsFormUnlisted,
            'technical': forms.AddonFormTechnicalUnlisted
        })

    if section not in models:
        raise http.Http404()

    tags, previews, restricted_tags = [], [], []
    cat_form = dependency_form = whiteboard_form = None
    whiteboard = None

    if section == 'describe' and show_listed:
        category_form_class = (forms.SingleCategoryForm if static_theme else
                               forms.CategoryFormSet)
        cat_form = category_form_class(
            request.POST or None, addon=addon, request=request)

    elif section == 'additional_details' and show_listed:
        tags = addon.tags.not_denied().values_list('tag_text', flat=True)
        restricted_tags = addon.tags.filter(restricted=True)

    elif section == 'media':
        previews = forms.PreviewFormSet(
            request.POST or None,
            prefix='files', queryset=addon.previews.all())

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
@dev_required
@json_view
def image_status(request, addon_id, addon):
    # Default icon needs no checking.
    if not addon.icon_type or addon.icon_type.split('/')[0] == 'icon':
        icons = True
    else:
        icons = storage.exists(os.path.join(addon.get_icon_dir(),
                                            '%s-32.png' % addon.id))
    previews = all(storage.exists(p.thumbnail_path)
                   for p in addon.previews.all())
    return {'overall': icons and previews,
            'icons': icons,
            'previews': previews}


@dev_required
@json_view
def upload_image(request, addon_id, addon, upload_type):
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
        is_preview = upload_type == 'preview'
        image_check = amo_utils.ImageCheck(upload_preview)
        is_animated = image_check.is_animated()  # will also cache .is_image()

        if (upload_preview.content_type not in amo.IMG_TYPES or
                not image_check.is_image()):
            if is_icon:
                errors.append(ugettext('Icons must be either PNG or JPG.'))
            else:
                errors.append(ugettext('Images must be either PNG or JPG.'))

        if is_animated:
            if is_icon:
                errors.append(ugettext('Icons cannot be animated.'))
            else:
                errors.append(ugettext('Images cannot be animated.'))

        if is_icon:
            max_size = settings.MAX_ICON_UPLOAD_SIZE
        else:
            max_size = None

        if max_size and upload_preview.size > max_size:
            if is_icon:
                errors.append(
                    ugettext('Please use images smaller than %dMB.')
                    % (max_size // 1024 // 1024))

        content_waffle = waffle.switch_is_active('content-optimization')
        if image_check.is_image() and content_waffle and is_preview:
            min_size = amo.ADDON_PREVIEW_SIZES.get('min')
            # * 100 to get a nice integer to compare against rather than 1.3333
            required_ratio = min_size[0] * 100 // min_size[1]
            actual_size = image_check.size
            actual_ratio = actual_size[0] * 100 // actual_size[1]
            if actual_size[0] < min_size[0] or actual_size[1] < min_size[1]:
                # L10n: {0} is an image width (in pixels), {1} is a height.
                errors.append(
                    ugettext('Image must be at least {0} pixels wide and {1} '
                             'pixels tall.').format(min_size[0], min_size[1]))
            if actual_ratio != required_ratio:
                errors.append(
                    ugettext('Image dimensions must be in the ratio 4:3.'))

        if image_check.is_image() and content_waffle and is_icon:
            standard_size = amo.ADDON_ICON_SIZES[-1]
            icon_size = image_check.size
            if icon_size[0] < standard_size or icon_size[1] < standard_size:
                # L10n: {0} is an image width/height (in pixels).
                errors.append(
                    ugettext(u'Icon must be at least {0} pixels wide and '
                             u'tall.').format(standard_size))
            if icon_size[0] != icon_size[1]:
                errors.append(
                    ugettext(u'Icon must be square (same width and height).'))

        if errors and is_preview and os.path.exists(loc):
            # Delete the temporary preview file in case of error.
            os.unlink(loc)
    else:
        errors.append(ugettext('There was an error uploading your preview.'))

    if errors:
        upload_hash = ''

    return {'upload_hash': upload_hash, 'errors': errors}


@dev_required
def version_edit(request, addon_id, addon, version_id):
    version = get_object_or_404(addon.versions.all(), pk=version_id)
    static_theme = addon.type == amo.ADDON_STATICTHEME
    version_form = forms.VersionForm(
        request.POST or None,
        request.FILES or None,
        instance=version,
        request=request,
    ) if not static_theme else None

    data = {}

    if version_form:
        data['version_form'] = version_form

    is_admin = acl.action_allowed(request,
                                  amo.permissions.REVIEWS_ADMIN)

    if not static_theme and addon.accepts_compatible_apps():
        qs = version.apps.all().select_related('min', 'max')
        compat_form = forms.CompatFormSet(
            request.POST or None, queryset=qs,
            form_kwargs={'version': version})
        data['compat_form'] = compat_form

    if (request.method == 'POST' and
            all([form.is_valid() for form in data.values()])):
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

            if 'approval_notes' in version_form.changed_data:
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

                commit_to_git = waffle.switch_is_active(
                    'enable-uploads-commit-to-git-storage')

                if commit_to_git:
                    # Extract into git repository
                    extract_version_source_to_git.delay(
                        version_id=data['version_form'].instance.pk,
                        author_id=request.user.pk)

                if had_pending_info_request:
                    log_and_notify(amo.LOG.SOURCE_CODE_UPLOADED, None,
                                   request.user, version)
                else:
                    ActivityLog.create(amo.LOG.SOURCE_CODE_UPLOADED,
                                       addon, version, request.user)

        messages.success(request, ugettext('Changes successfully saved.'))
        return redirect('devhub.versions.edit', addon.slug, version_id)

    data.update({
        'addon': addon,
        'version': version,
        'is_admin': is_admin,
        'choices': File.STATUS_CHOICES,
        'files': version.files.all()})

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
    version = get_object_or_404(addon.versions.all(), pk=version_id)
    if not version.can_be_disabled_and_deleted():
        # Developers shouldn't be able to delete/disable the current version
        # of an approved add-on.
        msg = ugettext(
            'The latest approved version of this Recommended extension cannot '
            'be deleted or disabled because the previous version was not '
            'approved for recommendation. '
            'Please contact AMO Admins if you need help with this.')
        messages.error(request, msg)
    elif 'disable_version' in request.POST:
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
    version = get_object_or_404(addon.versions.all(), pk=version_id)
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


@dev_required
def version_list(request, addon_id, addon):
    qs = addon.versions.order_by('-created')
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
    vs = addon.versions.filter(version=version).order_by('-created').first()
    if vs:
        return redirect('devhub.versions.edit', addon.slug, vs.id)
    else:
        raise http.Http404()


@json_view
@dev_required
def version_stats(request, addon_id, addon):
    qs = addon.versions.all()
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


@login_required
def submit_addon(request):
    return render_agreement(
        request=request,
        template='devhub/addons/submit/start.html',
        next_step='devhub.submit.distribution',
    )


@dev_required
def submit_version_agreement(request, addon_id, addon):
    return render_agreement(
        request=request,
        template='devhub/addons/submit/start.html',
        next_step=reverse('devhub.submit.version', args=(addon.slug,)),
        submit_page='version',
    )


@transaction.atomic
def _submit_distribution(request, addon, next_view):
    # Accept GET for the first load so we can preselect the channel, but only
    # when there is no addon or the add-on is not "invisible".
    if request.method == 'POST':
        data = request.POST
    elif 'channel' in request.GET and (
            not addon or not addon.disabled_by_user):
        data = request.GET
    else:
        data = None
    form = forms.DistributionChoiceForm(data, addon=addon)

    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        args = [addon.slug] if addon else []
        args.append(data['channel'])
        return redirect(next_view, *args)
    return render(request, 'devhub/addons/submit/distribute.html',
                  {'addon': addon, 'distribution_form': form,
                   'submit_notification_warning':
                       get_config('submit_notification_warning'),
                   'submit_page': 'version' if addon else 'addon'})


@login_required
def submit_addon_distribution(request):
    if not UploadRestrictionChecker(request).is_submission_allowed():
        return redirect('devhub.submit.agreement')
    return _submit_distribution(request, None, 'devhub.submit.upload')


@dev_required(submitting=True)
def submit_version_distribution(request, addon_id, addon):
    if not UploadRestrictionChecker(request).is_submission_allowed():
        return redirect('devhub.submit.version.agreement', addon.slug)
    return _submit_distribution(request, addon, 'devhub.submit.version.upload')


WIZARD_COLOR_FIELDS = [
    ('frame',
     _(u'Header area background'),
     _(u'The color of the header area background, displayed in the part of '
       u'the header not covered or visible through the header image. Manifest '
       u'field:  frame.'),
     'rgba(229,230,232,1)'),
    ('tab_background_text',
     _(u'Header area text and icons'),
     _(u'The color of the text and icons in the header area, except the '
       u'active tab. Manifest field:  tab_background_text.'),
     'rgba(0,0,0,1'),
    ('toolbar',
     _(u'Toolbar area background'),
     _(u'The background color for the navigation bar, the bookmarks bar, and '
       u'the selected tab.  Manifest field:  toolbar.'),
     False),
    ('bookmark_text',
     _(u'Toolbar area text and icons'),
     _(u'The color of the text and icons in the toolbar and the active tab. '
       u'Manifest field:  bookmark_text.'),
     False),
    ('toolbar_field',
     _(u'Toolbar field area background'),
     _(u'The background color for fields in the toolbar, such as the URL bar. '
       u'Manifest field:  toolbar_field.'),
     False),
    ('toolbar_field_text',
     _(u'Toolbar field area text'),
     _(u'The color of text in fields in the toolbar, such as the URL bar. '
       u'Manifest field:  toolbar_field_text.'),
     False)
]


@transaction.atomic
def _submit_upload(request, addon, channel, next_view, wizard=False):
    """ If this is a new addon upload `addon` will be None.

    next_view is the view that will be redirected to.
    """
    if (addon and addon.disabled_by_user and
            channel == amo.RELEASE_CHANNEL_LISTED):
        # Listed versions can not be submitted while the add-on is set to
        # "invisible" (disabled_by_user).
        return redirect('devhub.submit.version.distribution', addon.slug)
    form = forms.NewUploadForm(
        request.POST or None,
        request.FILES or None,
        addon=addon,
        request=request
    )
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data

        if addon:
            version = Version.from_upload(
                upload=data['upload'],
                addon=addon,
                selected_apps=data['compatible_apps'],
                channel=channel,
                parsed_data=data['parsed_data'])
            url_args = [addon.slug, version.id]
        else:
            addon = Addon.from_upload(
                upload=data['upload'],
                channel=channel,
                selected_apps=data['compatible_apps'],
                parsed_data=data['parsed_data'],
                user=request.user)
            version = addon.find_latest_version(channel=channel)
            url_args = [addon.slug]

        check_validation_override(request, form, addon, version)
        if (addon.status == amo.STATUS_NULL and
                addon.has_complete_metadata() and
                channel == amo.RELEASE_CHANNEL_LISTED):
            addon.update(status=amo.STATUS_NOMINATED)
        add_dynamic_theme_tag(version)
        return redirect(next_view, *url_args)
    is_admin = acl.action_allowed(request,
                                  amo.permissions.REVIEWS_ADMIN)
    if addon:
        channel_choice_text = (forms.DistributionChoiceForm().LISTED_LABEL
                               if channel == amo.RELEASE_CHANNEL_LISTED else
                               forms.DistributionChoiceForm().UNLISTED_LABEL)
    else:
        channel_choice_text = ''  # We only need this for Version upload.

    submit_page = 'version' if addon else 'addon'
    template = ('devhub/addons/submit/upload.html' if not wizard else
                'devhub/addons/submit/wizard.html')
    existing_properties = (
        extract_theme_properties(addon, channel)
        if wizard and addon else {})
    unsupported_properties = (
        wizard_unsupported_properties(
            existing_properties,
            [field for field, _, _, _ in WIZARD_COLOR_FIELDS])
        if existing_properties else [])
    return render(request, template,
                  {'new_addon_form': form,
                   'is_admin': is_admin,
                   'addon': addon,
                   'submit_notification_warning':
                       get_config('submit_notification_warning'),
                   'submit_page': submit_page,
                   'channel': channel,
                   'channel_choice_text': channel_choice_text,
                   'existing_properties': existing_properties,
                   'colors': WIZARD_COLOR_FIELDS,
                   'unsupported_properties': unsupported_properties,
                   'version_number':
                       get_next_version_number(addon) if wizard else None})


@login_required
def submit_addon_upload(request, channel):
    if not UploadRestrictionChecker(request).is_submission_allowed():
        return redirect('devhub.submit.agreement')
    channel_id = amo.CHANNEL_CHOICES_LOOKUP[channel]
    return _submit_upload(
        request, None, channel_id, 'devhub.submit.source')


@dev_required(submitting=True)
@no_admin_disabled
def submit_version_upload(request, addon_id, addon, channel):
    if not UploadRestrictionChecker(request).is_submission_allowed():
        return redirect('devhub.submit.version.agreement', addon.slug)
    channel_id = amo.CHANNEL_CHOICES_LOOKUP[channel]
    return _submit_upload(
        request, addon, channel_id, 'devhub.submit.version.source')


@dev_required
@no_admin_disabled
def submit_version_auto(request, addon_id, addon):
    if not UploadRestrictionChecker(request).is_submission_allowed():
        return redirect('devhub.submit.version.agreement', addon.slug)
    # Choose the channel we need from the last upload, unless that channel
    # would be listed and addon is set to "Invisible".
    last_version = addon.find_latest_version(None, exclude=())
    if not last_version or (
            last_version.channel == amo.RELEASE_CHANNEL_LISTED and
            addon.disabled_by_user):
        return redirect('devhub.submit.version.distribution', addon.slug)
    channel = last_version.channel
    return _submit_upload(
        request, addon, channel, 'devhub.submit.version.source')


@login_required
def submit_addon_theme_wizard(request, channel):
    if not UploadRestrictionChecker(request).is_submission_allowed():
        return redirect('devhub.submit.agreement')
    channel_id = amo.CHANNEL_CHOICES_LOOKUP[channel]
    return _submit_upload(
        request, None, channel_id, 'devhub.submit.source', wizard=True)


@dev_required
@no_admin_disabled
def submit_version_theme_wizard(request, addon_id, addon, channel):
    if not UploadRestrictionChecker(request).is_submission_allowed():
        return redirect('devhub.submit.version.agreement', addon.slug)
    channel_id = amo.CHANNEL_CHOICES_LOOKUP[channel]
    return _submit_upload(
        request, addon, channel_id, 'devhub.submit.version.source',
        wizard=True)


def _submit_source(request, addon, version, next_view):
    redirect_args = [addon.slug, version.pk] if version else [addon.slug]
    if addon.type != amo.ADDON_EXTENSION:
        return redirect(next_view, *redirect_args)
    latest_version = version or addon.find_latest_version(channel=None)

    form = forms.SourceForm(
        request.POST or None,
        request.FILES or None,
        instance=latest_version,
        request=request)
    if request.method == 'POST' and form.is_valid():
        if form.cleaned_data.get('source'):
            AddonReviewerFlags.objects.update_or_create(
                addon=addon, defaults={'needs_admin_code_review': True})

            activity_log = ActivityLog.objects.create(
                action=amo.LOG.SOURCE_CODE_UPLOADED.id,
                user=request.user,
                details={
                    'comments': (u'This version has been automatically '
                                 u'flagged for admin review, as it had source '
                                 u'files attached when submitted.')})
            VersionLog.objects.create(
                version_id=latest_version.id, activity_log=activity_log)
            form.save()

            # We can extract the actual source file only after the form
            # has been saved because the file behind it may not have been
            # written to disk yet (e.g for in-memory uploads)
            if waffle.switch_is_active('enable-uploads-commit-to-git-storage'):
                extract_version_source_to_git.delay(
                    version_id=form.instance.pk,
                    author_id=request.user.pk)

        return redirect(next_view, *redirect_args)
    context = {
        'form': form,
        'addon': addon,
        'version': version,
        'submit_page': 'version' if version else 'addon',
    }
    return render(request, 'devhub/addons/submit/source.html', context)


@dev_required(submitting=True)
def submit_addon_source(request, addon_id, addon):
    return _submit_source(request, addon, None, 'devhub.submit.details')


@dev_required(submitting=True)
def submit_version_source(request, addon_id, addon, version_id):
    version = get_object_or_404(addon.versions.all(), id=version_id)
    return _submit_source(
        request, addon, version, 'devhub.submit.version.details')


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
        'sources_provided': latest_version.sources_provided,
        'submit_page': 'version' if version else 'addon',
    }

    post_data = request.POST if request.method == 'POST' else None
    show_all_fields = not version or not addon.has_complete_metadata()

    if show_all_fields:
        if waffle.switch_is_active('content-optimization'):
            describe_form = forms.DescribeFormContentOptimization(
                post_data, instance=addon, request=request, version=version,
                should_auto_crop=True)
        else:
            describe_form = forms.DescribeForm(
                post_data, instance=addon, request=request, version=version)
        cat_form_class = (forms.CategoryFormSet if not static_theme
                          else forms.SingleCategoryForm)
        cat_form = cat_form_class(post_data, addon=addon, request=request)
        policy_form = forms.PolicyForm(post_data, addon=addon)
        license_form = forms.LicenseForm(
            post_data, version=latest_version, prefix='license')
        context.update(license_form.get_context())
        context.update(
            form=describe_form,
            cat_form=cat_form,
            policy_form=policy_form)
        forms_list.extend([
            describe_form,
            cat_form,
            policy_form,
            context['license_form']
        ])
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
            policy_form.save()
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
    version = get_object_or_404(addon.versions.all(), id=version_id)
    return _submit_details(request, addon, version)


def _submit_finish(request, addon, version):
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
            'addon_name': str(addon.name),
            'app': str(request.APP.pretty),
            'detail_url': absolutify(addon.get_url_path()),
            'version_url': absolutify(addon.get_dev_url('versions')),
            'edit_url': absolutify(addon.get_dev_url('edit')),
        }
        tasks.send_welcome_email.delay(addon.id, [author.email], context)

    submit_page = 'version' if version else 'addon'
    return render(request, 'devhub/addons/submit/done.html',
                  {'addon': addon,
                   'uploaded_version': uploaded_version,
                   'submit_page': submit_page,
                   'preview': uploaded_version.previews.first()})


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
    version = get_object_or_404(addon.versions.all(), id=version_id)
    return _submit_finish(request, addon, version)


@dev_required
@post_required
def remove_locale(request, addon_id, addon):
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
    return render_agreement(
        request=request,
        template='devhub/api/agreement.html',
        next_step='devhub.api_key',
    )


def render_agreement(request, template, next_step, **extra_context):
    form = forms.AgreementForm(
        request.POST if request.method == 'POST' else None,
        request=request
    )
    if request.method == 'POST' and form.is_valid():
        # Developer has validated the form: let's update its profile and
        # redirect to next step. Note that the form is supposed to always be
        # invalid if submission is not allowed for this request.
        data = {
            'read_dev_agreement': datetime.datetime.now(),
        }
        if 'display_name' in form.cleaned_data:
            data['display_name'] = form.cleaned_data['display_name']
        request.user.update(**data)
        return redirect(next_step)
    elif not UploadRestrictionChecker(request).is_submission_allowed():
        # Developer has either posted an invalid form or just landed on the
        # page but haven't read the agreement yet, or isn't allowed to submit
        # for some other reason (denied ip/email): show the form (with
        # potential errors highlighted)
        context = {
            'agreement_form': form,
            'agreement_message': str(
                DeveloperAgreementRestriction.error_message
            ),
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
    if not UploadRestrictionChecker(request).is_submission_allowed():
        return redirect(reverse('devhub.api_key_agreement'))

    try:
        credentials = APIKey.get_jwt_key(user=request.user)
    except APIKey.DoesNotExist:
        credentials = None

    try:
        confirmation = APIKeyConfirmation.objects.get(
            user=request.user)
    except APIKeyConfirmation.DoesNotExist:
        confirmation = None

    if request.method == 'POST':
        has_confirmed_or_is_confirming = confirmation and (
            confirmation.confirmed_once or confirmation.is_token_valid(
                request.POST.get('confirmation_token'))
        )

        # Revoking credentials happens regardless of action, if there were
        # credentials in the first place.
        if (credentials and
                request.POST.get('action') in ('revoke', 'generate')):
            credentials.update(is_active=None)
            log.info('revoking JWT key for user: {}, {}'
                     .format(request.user.id, credentials))
            send_key_revoked_email(request.user.email, credentials.key)
            msg = ugettext(
                'Your old credentials were revoked and are no longer valid.')
            messages.success(request, msg)

        # If trying to generate with no confirmation instance, we don't
        # generate the keys immediately but instead send you an email to
        # confirm the generation of the key. This should only happen once per
        # user, unless the instance is deleted by admins to reset the process
        # for that user.
        if confirmation is None and request.POST.get('action') == 'generate':
            confirmation = APIKeyConfirmation.objects.create(
                user=request.user, token=APIKeyConfirmation.generate_token())
            confirmation.send_confirmation_email()
        # If you have a confirmation instance, you need to either have it
        # confirmed once already or have the valid token proving you received
        # the email.
        elif (has_confirmed_or_is_confirming and
              request.POST.get('action') == 'generate'):
            confirmation.update(confirmed_once=True)
            new_credentials = APIKey.new_jwt_credentials(request.user)
            log.info('new JWT key created: {}'.format(new_credentials))
            send_key_change_email(request.user.email, new_credentials.key)
        else:
            # If we land here, either confirmation token is invalid, or action
            # is invalid, or state is outdated (like user trying to revoke but
            # there are already no credentials).
            # We can just pass and let the redirect happen.
            pass

        # In any case, redirect after POST.
        return redirect(reverse('devhub.api_key'))

    context_data = {
        'title': ugettext('Manage API Keys'),
        'credentials': credentials,
        'confirmation': confirmation,
        'token': request.GET.get('token')  # For confirmation step.
    }

    return render(request, 'devhub/api/key.html', context_data)


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


@dev_required
@json_view
def theme_background_image(request, addon_id, addon, channel):
    channel_id = amo.CHANNEL_CHOICES_LOOKUP[channel]
    version = addon.find_latest_version(channel_id)
    return (version.get_background_images_encoded(header_only=True) if version
            else {})


def logout(request):
    user = request.user
    if not user.is_anonymous:
        log.debug('User (%s) logged out' % user)

    if 'to' in request.GET and not _is_safe_url(request.GET['to'], request):
        log.info('Unsafe redirect to %s' % request.GET['to'])
        gets = request.GET.copy()
        gets['to'] = settings.LOGIN_REDIRECT_URL
        request.GET = gets

    next_url = request.GET.get('to')
    if not next_url:
        next_url = settings.LOGOUT_REDIRECT_URL
        prefixer = get_url_prefix()
        if prefixer:
            next_url = prefixer.fix(next_url)

    response = http.HttpResponseRedirect(next_url)

    logout_user(request, response)

    return response
