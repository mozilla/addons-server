import datetime
import json
import os
import time
from copy import deepcopy
from urllib.parse import quote, urlencode, urljoin
from uuid import UUID, uuid4

from django import forms as django_forms, http
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage as storage
from django.db import transaction
from django.db.models import Count, F, Func, OuterRef, Subquery
from django.db.utils import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template import loader
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext, gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

import waffle
from csp.decorators import csp_update
from django_statsd.clients import statsd

import olympia.core.logger
from olympia import amo
from olympia.access import acl
from olympia.accounts.decorators import two_factor_auth_required
from olympia.accounts.utils import (
    redirect_for_login,
    redirect_for_login_with_2fa_enforced,
)
from olympia.accounts.views import logout_user
from olympia.activity.models import ActivityLog, CommentLog
from olympia.addons.decorators import require_submissions_enabled
from olympia.addons.models import (
    Addon,
    AddonApprovalsCounter,
    AddonReviewerFlags,
    AddonUser,
    AddonUserPendingConfirmation,
)
from olympia.addons.views import BaseFilter
from olympia.amo import messages, utils as amo_utils
from olympia.amo.decorators import json_view, login_required, post_required
from olympia.amo.reverse import get_url_prefix
from olympia.amo.templatetags.jinja_helpers import absolutify, urlparams
from olympia.amo.utils import (
    MenuItem,
    StopWatch,
    escape_all,
    is_safe_url,
    send_mail,
    send_mail_jinja,
)
from olympia.devhub.decorators import (
    dev_required,
    no_admin_disabled,
    two_factor_auth_required_if_non_theme,
)
from olympia.devhub.file_validation_annotations import insert_validation_message
from olympia.devhub.models import BlogPost, RssKey, SurveyResponse
from olympia.devhub.utils import (
    extract_theme_properties,
    wizard_unsupported_properties,
)
from olympia.files.models import File, FileUpload
from olympia.files.utils import parse_addon
from olympia.reviewers.forms import PublicWhiteboardForm
from olympia.reviewers.models import Whiteboard
from olympia.reviewers.utils import ReviewHelper
from olympia.users.models import (
    SuppressedEmailVerification,
)
from olympia.users.tasks import send_suppressed_email_confirmation
from olympia.users.utils import (
    RestrictionChecker,
    check_suppressed_email_confirmation,
    send_addon_author_add_mail,
    send_addon_author_change_mail,
    send_addon_author_remove_mail,
)
from olympia.versions.models import Version
from olympia.versions.tasks import duplicate_addon_version_for_rollback
from olympia.versions.utils import get_next_version_number
from olympia.zadmin.models import get_config

from . import feeds, forms, tasks


log = olympia.core.logger.getLogger('z.devhub')


# We use a session cookie to make sure people see the dev agreement.

MDN_BASE = 'https://developer.mozilla.org/en-US/Add-ons'


def get_fileupload_by_uuid_or_40x(value, *, user):
    try:
        UUID(value)
    except ValueError as exc:
        raise http.Http404() from exc
    upload = get_object_or_404(FileUpload, uuid=value)
    if upload.user != user:
        raise PermissionDenied
    return upload


class AddonFilter(BaseFilter):
    opts = (
        ('updated', _('Updated')),
        ('name', _('Name')),
        ('created', _('Created')),
        ('popular', _('Downloads')),
        ('rating', _('Rating')),
    )


class ThemeFilter(BaseFilter):
    opts = (
        ('created', _('Created')),
        ('name', _('Name')),
        ('popular', _('Downloads')),
        ('rating', _('Rating')),
    )


def addon_listing(request, theme=False):
    """Set up the queryset and filtering for addon listing for Dashboard."""
    if theme:
        qs = request.user.addons.filter(type=amo.ADDON_STATICTHEME)
        filter_cls = ThemeFilter
        default = 'created'
    else:
        qs = request.user.addons.exclude(type=amo.ADDON_STATICTHEME)
        filter_cls = AddonFilter
        default = 'updated'
    filter_ = filter_cls(request, qs, 'sort', default)
    return filter_.qs, filter_


@csp_update(
    {
        'connect-src': [settings.MOZILLA_NEWLETTER_URL],
        'form-action': [settings.MOZILLA_NEWLETTER_URL],
    }
)
def index(request):
    ctx = {}
    if request.user.is_authenticated:
        recent_addons = request.user.addons.all().order_by('-modified')[:3]
        ctx['recent_addons'] = recent_addons

    return TemplateResponse(request, 'devhub/index.html', context=ctx)


@login_required
def dashboard(request, theme=False):
    addon_items = _get_items(None, request.user.addons.all())[:4]

    data = dict(
        rss=_get_rss_feed(request),
        blog_posts=_get_posts(),
        timestamp=int(time.time()),
        addon_tab=not theme,
        theme=theme,
        addon_items=addon_items,
    )
    if data['addon_tab']:
        addons, data['filter'] = addon_listing(request)
        data['addons'] = amo_utils.paginate(request, addons, per_page=10)

    if theme:
        themes, data['filter'] = addon_listing(request, theme=True)
        data['themes'] = amo_utils.paginate(request, themes, per_page=10)

    if 'filter' in data:
        data['sorting'] = data['filter'].field
        data['sort_opts'] = data['filter'].opts

    return TemplateResponse(request, 'devhub/addons/dashboard.html', context=data)


def _get_addons(request, addons, addon_id, action):
    """Create a list of ``MenuItem``s for the activity feed."""
    items = []

    a = MenuItem()
    a.selected = not addon_id
    (a.text, a.url) = (gettext('All My Add-ons'), reverse('devhub.feed_all'))
    if action:
        a.url += '?action=' + action
    items.append(a)

    for addon in addons:
        item = MenuItem()
        try:
            item.selected = addon_id and addon.id == int(addon_id)
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
    text = {
        None: gettext('All Activity'),
        'updates': gettext('Add-on Updates'),
        'status': gettext('Add-on Status'),
        'collections': gettext('User Collections'),
        'reviews': gettext('User Reviews'),
    }

    items = []
    for c in choices:
        i = MenuItem()
        i.text = text[c]
        i.url, i.selected = urlparams(url, page=None, action=c), (action == c)
        items.append(i)

    return items


def _get_items(action, addons):
    if not isinstance(addons, (list, tuple)):
        # MySQL 8.0.21 (and maybe higher) doesn't optimize the join with
        # double # subquery the ActivityLog.objects.for_addons(addons) below
        # would generate if addons is not transformed into a list first. Since
        # some people have a lot of add-ons, we only take the last 100.
        addons = list(
            addons.all().order_by('-modified').values_list('pk', flat=True)[:100]
        )

    filters = {
        'updates': (amo.LOG.ADD_VERSION, amo.LOG.ADD_FILE_TO_VERSION),
        'status': (
            amo.LOG.USER_DISABLE,
            amo.LOG.USER_ENABLE,
            amo.LOG.CHANGE_STATUS,
            amo.LOG.APPROVE_VERSION,
        ),
        'collections': (
            amo.LOG.ADD_TO_COLLECTION,
            amo.LOG.REMOVE_FROM_COLLECTION,
        ),
        'reviews': (amo.LOG.ADD_RATING,),
    }

    filter_ = filters.get(action)
    items = (
        ActivityLog.objects.for_addons(addons)
        .exclude(action__in=amo.LOG_HIDE_DEVELOPER)
        .transform(ActivityLog.transformer_anonymize_user_for_developer)
    )
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
        addons_all = request.user.addons.all()

        if addon_id:
            addon = get_object_or_404(Addon.objects.id_or_slug(addon_id))
            try:
                key = RssKey.objects.get(addon=addon)
            except RssKey.DoesNotExist:
                key = RssKey.objects.create(addon=addon)

            addon_selected = addon.id

            rssurl = urlparams(
                reverse('devhub.feed', args=[addon_id]), privaterss=key.key.hex
            )

            if not acl.check_addon_ownership(
                request.user,
                addon,
                allow_developer=True,
                allow_mozilla_disabled_addon=True,
            ):
                raise PermissionDenied
            addons = [addon]
        else:
            rssurl = _get_rss_feed(request)
            addon = None
            addons = addons_all

    action = request.GET.get('action')

    items = _get_items(action, addons)

    activities = _get_activities(request, action)
    addon_items = _get_addons(request, addons_all, addon_selected, action)

    pager = amo_utils.paginate(request, items, 20)
    data = {
        'addons': addon_items,
        'pager': pager,
        'activities': activities,
        'rss': rssurl,
        'addon': addon,
    }
    return TemplateResponse(request, 'devhub/addons/activity.html', context=data)


@dev_required
def edit(request, addon_id, addon):
    try:
        whiteboard = Whiteboard.objects.get(pk=addon.pk)
    except Whiteboard.DoesNotExist:
        whiteboard = Whiteboard(pk=addon.pk)

    previews = (
        addon.current_version.previews.all()
        if addon.current_version and addon.has_per_version_previews
        else addon.previews.all()
    )
    header_preview = (
        previews.first()
        if addon.type == amo.ADDON_STATICTHEME and addon.status != amo.STATUS_DISABLED
        else None
    )
    data = {
        'page': 'edit',
        'addon': addon,
        'whiteboard': whiteboard,
        'editable': False,
        'show_listed_fields': addon.has_listed_versions(),
        'valid_slug': addon.slug,
        'tags': addon.tags.values_list('tag_text', flat=True),
        'previews': previews,
        'header_preview': header_preview,
        'supported_image_types': amo.SUPPORTED_IMAGE_TYPES,
    }

    return TemplateResponse(request, 'devhub/addons/edit.html', context=data)


@dev_required(owner_for_post=True)
@post_required
def delete(request, addon_id, addon):
    # Database deletes only allowed for free or incomplete addons.
    if not addon.can_be_deleted():
        msg = gettext('Add-on cannot be deleted. Disable this add-on instead.')
        messages.error(request, msg)
        return redirect(addon.get_dev_url('versions'))

    any_theme = addon.type == amo.ADDON_STATICTHEME
    form = forms.DeleteForm(request.POST, addon=addon)
    if form.is_valid():
        reason = form.cleaned_data.get('reason', '')
        addon.delete(msg='Removed via devhub', reason=reason)
        messages.success(
            request,
            gettext('Theme deleted.') if any_theme else gettext('Add-on deleted.'),
        )
        return redirect('devhub.%s' % ('themes' if any_theme else 'addons'))
    else:
        messages.error(
            request,
            gettext('URL name was incorrect. Theme was not deleted.')
            if any_theme
            else gettext('URL name was incorrect. Add-on was not deleted.'),
        )
        return redirect(addon.get_dev_url('versions'))


@dev_required
@post_required
def enable(request, addon_id, addon):
    addon.update(disabled_by_user=False)
    ActivityLog.objects.create(amo.LOG.USER_ENABLE, addon)
    return redirect(addon.get_dev_url('versions'))


@dev_required(owner_for_post=True)
@post_required
def cancel(request, addon_id, addon, channel):
    channel = amo.CHANNEL_CHOICES_LOOKUP[channel]
    latest_version = addon.find_latest_version(channel=channel)
    if latest_version:
        if latest_version.file.status == amo.STATUS_AWAITING_REVIEW:
            latest_version.is_user_disabled = True  # Will update the files/activity log
        addon.update_status()
    return redirect(addon.get_dev_url('versions'))


@dev_required
@post_required
def disable(request, addon_id, addon):
    addon.update(disabled_by_user=True)
    ActivityLog.objects.create(amo.LOG.USER_DISABLE, addon)
    return redirect(addon.get_dev_url('versions'))


@dev_required
@post_required
def rejected_review_request(request, addon_id, addon):
    if addon.status != amo.STATUS_REJECTED:
        raise http.Http404()
    AddonApprovalsCounter.request_new_content_review_for_addon(addon)
    ActivityLog.objects.create(amo.LOG.REJECTED_LISTING_REVIEW_REQUEST, addon)
    messages.success(
        request,
        gettext('Request for a new review of listing content acknowledged.'),
    )
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
            addon=addon, user=request.user
        )
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
            last_position = (
                AddonUser.objects.filter(addon=invitation.addon)
                .order_by('position')
                .values_list('position', flat=True)
                .last()
                or 0
            )
            AddonUser.unfiltered.update_or_create(
                addon=invitation.addon,
                user=invitation.user,
                defaults={
                    'role': invitation.role,
                    'listed': invitation.listed,
                    'position': last_position + 1,
                },
            )
            messages.success(request, gettext('Invitation accepted.'))
            redirect_url = addon.get_dev_url()
        else:
            messages.success(request, gettext('Invitation declined.'))
            redirect_url = reverse('devhub.addons')
        # Regardless of whether or not the invitation was accepted or not,
        # it's now obsolete.
        invitation.delete()
        return redirect(redirect_url)
    ctx = {
        'addon': addon,
        'invitation': invitation,
    }
    return TemplateResponse(request, 'devhub/addons/invitation.html', context=ctx)


@dev_required(owner_for_post=True)
def ownership(request, addon_id, addon):
    fs = []
    ctx = {
        'addon': addon,
        # Override editable_body_class, because this page is not editable by
        # regular developers, but can be edited by owners even if it's a site
        # permission add-on.
        'editable_body_class': 'no-edit'
        if not acl.check_addon_ownership(request.user, addon)
        else '',
    }
    post_data = request.POST if request.method == 'POST' else None
    # Authors.
    user_form = forms.AuthorFormSet(
        post_data,
        prefix='user_form',
        queryset=AddonUser.objects.filter(addon=addon).order_by('position'),
        form_kwargs={'addon': addon},
    )
    fs.append(user_form)
    ctx['user_form'] = user_form
    # Authors pending confirmation (owner can still remove them before they
    # accept).
    authors_pending_confirmation_form = forms.AuthorWaitingConfirmationFormSet(
        post_data,
        prefix='authors_pending_confirmation',
        queryset=AddonUserPendingConfirmation.objects.filter(addon=addon).order_by(
            'id'
        ),
        form_kwargs={'addon': addon},
    )
    fs.append(authors_pending_confirmation_form)
    ctx['authors_pending_confirmation_form'] = authors_pending_confirmation_form
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

    def process_author_changes(source_form, existing_authors_emails):
        addon_users_to_process = source_form.save(commit=False)
        for addon_user in addon_users_to_process:
            addon_user.addon = addon
            if not addon_user.pk:
                send_addon_author_add_mail(addon_user, existing_authors_emails)
                messages.success(
                    request,
                    gettext('A confirmation email has been sent to {email}').format(
                        email=addon_user.user.email
                    ),
                )
            elif addon_user.role != addon_user._initial_attrs.get('role'):
                send_addon_author_change_mail(addon_user, existing_authors_emails)
            addon_user.save()
        for addon_user in source_form.deleted_objects:
            send_addon_author_remove_mail(addon_user, existing_authors_emails)
            addon_user.delete()

    if request.method == 'POST' and all([form.is_valid() for form in fs]):
        if license_form in fs:
            license_form.save()
        if policy_form and policy_form in fs:
            policy_form.save()
            ActivityLog.objects.create(amo.LOG.EDIT_PROPERTIES, addon)
        messages.success(request, gettext('Changes successfully saved.'))

        existing_authors_emails = list(addon.authors.values_list('email', flat=True))

        process_author_changes(
            authors_pending_confirmation_form, existing_authors_emails
        )
        process_author_changes(user_form, existing_authors_emails)

        return redirect(addon.get_dev_url('owner'))

    return TemplateResponse(request, 'devhub/addons/owner.html', context=ctx)


@login_required
def validate_addon(request):
    return TemplateResponse(
        request,
        'devhub/validate_addon.html',
        context={
            'title': gettext('Validate Add-on'),
            'new_addon_form': forms.DistributionChoiceForm(),
            'max_upload_size': settings.MAX_UPLOAD_SIZE,
        },
    )


def handle_upload(
    *,
    filedata,
    request,
    channel,
    addon=None,
    is_standalone=False,
    submit=False,
    source=amo.UPLOAD_SOURCE_DEVHUB,
    theme_specific=False,
):
    upload = FileUpload.from_post(
        filedata,
        filename=filedata.name,
        size=filedata.size,
        addon=addon,
        channel=channel,
        source=source,
        user=request.user,
    )
    if submit:
        tasks.validate_and_submit(
            addon=addon,
            upload=upload,
            theme_specific=theme_specific,
            client_info=request.META.get('HTTP_USER_AGENT'),
        )
    else:
        tasks.validate(upload, theme_specific=theme_specific)
    return upload


@login_required
@post_required
@require_submissions_enabled
def upload(request, channel='listed', addon=None, is_standalone=False):
    channel_as_text = channel
    channel = amo.CHANNEL_CHOICES_LOOKUP[channel]
    filedata = request.FILES['upload']
    theme_specific = django_forms.BooleanField().to_python(
        request.POST.get('theme_specific')
    )
    if (
        not theme_specific
        and not is_standalone
        and not request.session.get('has_two_factor_authentication')
    ):
        # This shouldn't happen: it means the user attempted to use the add-on
        # submission flow that is behind @two_factor_auth_required decorator
        # but didn't log in with 2FA. Because this view is used to serve an XHR
        # we return a fake validation error suggesting to enable 2FA instead of
        # redirecting.
        next_path = (
            reverse('devhub.submit.version.upload', args=[addon.slug, channel_as_text])
            if addon
            else reverse('devhub.submit.upload', args=[channel_as_text])
        )
        url = redirect_for_login_with_2fa_enforced(request, next_path=next_path)[
            'location'
        ]
        results = deepcopy(amo.VALIDATOR_SKELETON_RESULTS)
        insert_validation_message(
            results,
            message=_(
                '<a href="{link}">Please add two-factor authentication to your account '
                'to submit extensions.</a>'
            ).format(link=absolutify(url)),
        )
        return JsonResponse({'validation': results}, status=400)

    try:
        upload = handle_upload(
            filedata=filedata,
            request=request,
            addon=addon,
            is_standalone=is_standalone,
            channel=channel,
            theme_specific=theme_specific,
        )
    except django_forms.ValidationError as exc:
        # handle_upload() should be firing tasks to do validation. If it raised
        # a ValidationError, that means we failed before even reaching those
        # tasks, and need to return an error response immediately.
        results = deepcopy(amo.VALIDATOR_SKELETON_RESULTS)
        insert_validation_message(results, message=exc.message)
        return JsonResponse({'validation': results}, status=400)
    if addon:
        return redirect('devhub.upload_detail_for_version', addon.slug, upload.uuid.hex)
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
    upload = get_fileupload_by_uuid_or_40x(uuid, user=request.user)
    url = reverse('devhub.standalone_upload_detail', args=[uuid])
    return upload_validation_context(request, upload, url=url)


@dev_required(submitting=True)
@json_view
def upload_detail_for_version(request, addon_id, addon, uuid):
    try:
        upload = get_fileupload_by_uuid_or_40x(uuid, user=request.user)
        response = json_upload_detail(request, upload, addon_slug=addon.slug)
        statsd.incr('devhub.upload_detail_for_addon.success')
        return response
    except Exception as exc:
        statsd.incr('devhub.upload_detail_for_addon.error')
        log.error(f'Error checking upload status: {type(exc)} {exc}')
        raise


@dev_required(allow_reviewers_for_read=True)
def file_validation(request, addon_id, addon, file_id):
    file_ = get_object_or_404(File, version__addon=addon, id=file_id)

    validate_url = reverse('devhub.json_file_validation', args=[addon.slug, file_.id])

    context = {
        'validate_url': validate_url,
        'file': file_,
        'filename': file_.pretty_filename,
        'timestamp': file_.created,
        'addon': addon,
    }

    if file_.has_been_validated:
        context['validation_data'] = file_.validation.processed_validation

    return TemplateResponse(request, 'devhub/validation.html', context=context)


@csrf_exempt
# This allows read-only access to deleted add-ons for reviewers
# but not developers.
@dev_required(allow_reviewers_for_read=True, qs=Addon.unfiltered.all)
def json_file_validation(request, addon_id, addon, file_id):
    file = get_object_or_404(File, version__addon=addon, id=file_id)
    try:
        result = file.validation
    except File.validation.RelatedObjectDoesNotExist as exc:
        raise http.Http404 from exc
    return JsonResponse(
        {
            'validation': result.processed_validation,
            'error': None,
        }
    )


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
                    i,
                    {
                        'type': 'error',
                        # Actual validation messages coming from the linter are
                        # already escaped because they are coming from
                        # `processed_validation`, but we need to do that for
                        # those coming from ValidationError exceptions as well.
                        'message': escape_all(msg),
                        'tier': 1,
                        'fatal': True,
                    },
                )
                if result['validation']['ending_tier'] < 1:
                    result['validation']['ending_tier'] = 1
                result['validation']['errors'] += 1
            return json_view.error(result)
        else:
            result['addon_type'] = pkg.get('type', '')
            result['explicitly_compatible_with_android'] = pkg.get(
                'explicitly_compatible_with_android', False
            )
    return result


def upload_validation_context(request, upload, addon=None, url=None):
    if not url:
        if addon:
            url = reverse(
                'devhub.upload_detail_for_version', args=[addon.slug, upload.uuid.hex]
            )
        else:
            url = reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json'])
    full_report_url = reverse('devhub.upload_detail', args=[upload.uuid.hex])

    validation = upload.processed_validation or ''

    return {
        'upload': upload.uuid.hex,
        'validation': validation,
        'error': None,
        'url': url,
        'full_report_url': full_report_url,
    }


@login_required
def upload_detail(request, uuid, format='html'):
    upload = get_fileupload_by_uuid_or_40x(uuid, user=request.user)

    if format == 'json':
        try:
            response = json_upload_detail(request, upload)
            statsd.incr('devhub.upload_detail.success')
            return response
        except Exception as exc:
            statsd.incr('devhub.upload_detail.error')
            log.error(f'Error checking upload status: {type(exc)} {exc}')
            raise

    validate_url = reverse('devhub.standalone_upload_detail', args=[upload.uuid.hex])

    context = {
        'validate_url': validate_url,
        'filename': upload.pretty_name,
        'timestamp': upload.created,
    }

    if upload.validation:
        context['validation_data'] = upload.processed_validation

    return TemplateResponse(request, 'devhub/validation.html', context=context)


@dev_required
def addons_section(request, addon_id, addon, section, editable=False):
    show_listed = addon.has_listed_versions()
    static_theme = addon.type == amo.ADDON_STATICTHEME
    models = {}
    content_waffle = waffle.switch_is_active('content-optimization')
    if show_listed:
        models.update(
            {
                'describe': (
                    forms.DescribeForm
                    if not content_waffle
                    else forms.DescribeFormContentOptimization
                ),
                'additional_details': forms.AdditionalDetailsForm,
                'technical': forms.AddonFormTechnical,
            }
        )
        if not static_theme and addon.status != amo.STATUS_DISABLED:
            models.update({'media': forms.AddonFormMedia})
    else:
        models.update(
            {
                'describe': (
                    forms.DescribeFormUnlisted
                    if not content_waffle
                    else forms.DescribeFormUnlistedContentOptimization
                ),
                'additional_details': forms.AdditionalDetailsFormUnlisted,
                'technical': forms.AddonFormTechnicalUnlisted,
            }
        )

    if section not in models:
        raise http.Http404()

    tags, previews = [], []
    cat_form = dependency_form = whiteboard_form = None
    whiteboard = None

    if section == 'describe' and show_listed:
        cat_form = forms.CategoryForm(
            request.POST if request.method == 'POST' else None,
            addon=addon,
            request=request,
        )

    elif section == 'additional_details':
        tags = addon.tags.values_list('tag_text', flat=True)

    elif section == 'media':
        previews = forms.PreviewFormSet(
            request.POST or None, prefix='files', queryset=addon.previews.all()
        )

    if section == 'technical':
        try:
            whiteboard = Whiteboard.objects.get(pk=addon.pk)
        except Whiteboard.DoesNotExist:
            whiteboard = Whiteboard(pk=addon.pk)

        whiteboard_form = PublicWhiteboardForm(
            request.POST or None, instance=whiteboard, prefix='whiteboard'
        )

    # Get the slug before the form alters it to the form data.
    valid_slug = addon.slug
    if editable:
        if request.method == 'POST':
            main_form = models[section](
                request.POST, request.FILES, instance=addon, request=request
            )

            if main_form.is_valid() and (not previews or previews.is_valid()):
                addon = main_form.save(addon)

                if previews:
                    for preview in previews.forms:
                        preview.save(addon)

                editable = False
                if section == 'media':
                    ActivityLog.objects.create(amo.LOG.CHANGE_MEDIA, addon)
                else:
                    metadata_changes = getattr(main_form, 'metadata_changes', {})
                    for field, addedremoved in metadata_changes.items():
                        ActivityLog.objects.create(
                            amo.LOG.EDIT_ADDON_PROPERTY,
                            addon,
                            field,
                            json.dumps(addedremoved),
                        )

                    ActivityLog.objects.create(amo.LOG.EDIT_PROPERTIES, addon)

                if valid_slug != addon.slug:
                    ActivityLog.objects.create(
                        amo.LOG.ADDON_SLUG_CHANGED, addon, valid_slug, addon.slug
                    )
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
            main_form = models[section](instance=addon, request=request)
    else:
        main_form = False

    data = {
        'addon': addon,
        'whiteboard': whiteboard,
        'show_listed_fields': show_listed,
        'main_form': main_form,
        'editable': editable,
        'tags': tags,
        'cat_form': cat_form,
        'preview_form': previews,
        'dependency_form': dependency_form,
        'whiteboard_form': whiteboard_form,
        'valid_slug': valid_slug,
        'supported_image_types': amo.SUPPORTED_IMAGE_TYPES,
    }

    return TemplateResponse(
        request, 'devhub/addons/edit/%s.html' % section, context=data
    )


@never_cache
@dev_required
@json_view
def image_status(request, addon_id, addon):
    # Default icon needs no checking.
    if not addon.icon_type:
        icons = True
    else:
        icons = storage.exists(
            os.path.join(addon.get_icon_dir(), '%s-32.png' % addon.id)
        )
    previews = all(storage.exists(p.thumbnail_path) for p in addon.previews.all())
    return {'overall': icons and previews, 'icons': icons, 'previews': previews}


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

        if (
            upload_preview.content_type not in amo.IMG_TYPES
            or not image_check.is_image()
        ):
            if is_icon:
                errors.append(gettext('Icons must be either PNG or JPG.'))
            else:
                errors.append(gettext('Images must be either PNG or JPG.'))

        if is_animated:
            if is_icon:
                errors.append(gettext('Icons cannot be animated.'))
            else:
                errors.append(gettext('Images cannot be animated.'))

        if is_icon:
            max_size = settings.MAX_ICON_UPLOAD_SIZE
        else:
            max_size = settings.MAX_IMAGE_UPLOAD_SIZE

        if upload_preview.size > max_size:
            errors.append(
                gettext('Please use images smaller than %dMB.')
                % (max_size // 1024 // 1024)
            )

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
                    gettext(
                        'Image must be at least {0} pixels wide and {1} pixels tall.'
                    ).format(min_size[0], min_size[1])
                )
            if actual_ratio != required_ratio:
                errors.append(gettext('Image dimensions must be in the ratio 4:3.'))

        if image_check.is_image() and content_waffle and is_icon:
            standard_size = amo.ADDON_ICON_SIZES[-1]
            icon_size = image_check.size
            if icon_size[0] < standard_size or icon_size[1] < standard_size:
                # L10n: {0} is an image width/height (in pixels).
                errors.append(
                    gettext('Icon must be at least {0} pixels wide and tall.').format(
                        standard_size
                    )
                )
            if icon_size[0] != icon_size[1]:
                errors.append(gettext('Icon must be square (same width and height).'))

        if errors and is_preview and os.path.exists(loc):
            # Delete the temporary preview file in case of error.
            os.unlink(loc)
    else:
        errors.append(gettext('There was an error uploading your preview.'))

    if errors:
        upload_hash = ''

    return {'upload_hash': upload_hash, 'errors': errors}


@dev_required
def version_edit(request, addon_id, addon, version_id):
    version = get_object_or_404(addon.versions.all(), pk=version_id)
    posting = request.method == 'POST'
    static_theme = addon.type == amo.ADDON_STATICTHEME
    version_form = (
        forms.VersionForm(
            request.POST or None,
            request.FILES or None,
            instance=version,
        )
        if not static_theme
        else None
    )

    data = {}

    has_source = version_form and version_form['source'].data
    if version_form:
        data['version_form'] = version_form
        if has_source and posting:
            timer = StopWatch('devhub.views.version_edit.')
            timer.start()
            log.info(
                'version_edit, form populated, addon.slug: %s, version.id: %s',
                addon.slug,
                version.id,
            )
            timer.log_interval('1.form_populated')

    is_admin = acl.action_allowed_for(request.user, amo.permissions.REVIEWS_ADMIN)

    if not static_theme and addon.can_set_compatibility:
        qs = version.apps.all().select_related('min', 'max')
        compat_form = forms.CompatFormSet(
            request.POST or None, queryset=qs, form_kwargs={'version': version}
        )
        data['compat_form'] = compat_form

    if request.method == 'POST' and all([form.is_valid() for form in data.values()]):
        if has_source:
            log.info(
                'version_edit, form validated, addon.slug: %s, version.id: %s',
                addon.slug,
                version.id,
            )
            timer.log_interval('2.form_validated')
        if 'compat_form' in data:
            for compat in data['compat_form'].save(commit=False):
                if data['compat_form'].has_changed():
                    compat.originated_from = amo.APPVERSIONS_ORIGINATED_FROM_DEVELOPER
                    compat.version = version
                    compat.save()

            for compat in data['compat_form'].deleted_objects:
                compat.delete()

            for form in data['compat_form'].forms:
                if isinstance(form, forms.CompatForm) and 'max' in form.changed_data:
                    _log_max_version_change(addon, version, form.instance)

        if 'version_form' in data:
            data['version_form'].save()
            if has_source:
                log.info(
                    'version_edit, form saved, addon.slug: %s, version.id: %s',
                    addon.slug,
                    version.id,
                )
                timer.log_interval('3.form_saved')

            if 'approval_notes' in version_form.changed_data:
                ActivityLog.objects.create(
                    amo.LOG.NOTES_FOR_REVIEWERS_CHANGED, addon, version, request.user
                )

            if (
                'source' in version_form.changed_data
                and version_form.cleaned_data['source']
            ):
                version.flag_if_sources_were_provided(request.user)

        messages.success(request, gettext('Changes successfully saved.'))
        result = redirect('devhub.versions.edit', addon.slug, version_id)
        if has_source:
            log.info(
                'version_edit, redirecting to next view, '
                + 'addon.slug: %s, version.id: %s',
                addon.slug,
                version.id,
            )
            timer.log_interval('4.redirecting_to_next_view')

        return result

    data.update(
        {
            'addon': addon,
            'version': version,
            'is_admin': is_admin,
            'choices': File.STATUS_CHOICES,
            'files': (version.file,),
        }
    )

    if has_source and posting:
        log.info(
            'version_edit, validation failed, re-displaying the template, '
            + 'addon.slug: %s, version.id: %s',
            addon.slug,
            version.id,
        )
        timer.log_interval('5.validation_failed_re-displaying_the_template')
    return TemplateResponse(request, 'devhub/versions/edit.html', context=data)


def _log_max_version_change(addon, version, appversion):
    details = {
        'version': version.version,
        'target': appversion.version.version,
        'application': appversion.application,
    }
    ActivityLog.objects.create(
        amo.LOG.MAX_APPVERSION_UPDATED, addon, version, details=details
    )


@dev_required
@post_required
@transaction.atomic
def version_delete(request, addon_id, addon):
    version_id = request.POST.get('version_id')
    version = get_object_or_404(addon.versions.all(), pk=version_id)
    if not version.can_be_disabled_and_deleted():
        # Developers shouldn't be able to delete/disable the current version
        # of a promoted approved add-on.
        group = addon.promoted_groups()
        msg = gettext(
            'The latest approved version of this %s add-on cannot '
            'be deleted or disabled because the previous version was not '
            'approved for %s promotion. '
            'Please contact AMO Admins if you need help with this.'
        ) % (group.name, group.name)
        messages.error(request, msg)
    elif 'disable_version' in request.POST:
        messages.success(request, gettext('Version %s disabled.') % version.version)
        version.is_user_disabled = True  # Will update the files/activity log.
        version.addon.update_status()
    else:
        messages.success(request, gettext('Version %s deleted.') % version.version)
        version.delete()  # Will also activity log.
    return redirect(addon.get_dev_url('versions'))


@dev_required
@post_required
@transaction.atomic
def version_reenable(request, addon_id, addon):
    version_id = request.POST.get('version_id')
    version = get_object_or_404(addon.versions.all(), pk=version_id)
    messages.success(request, gettext('Version %s re-enabled.') % version.version)
    version.is_user_disabled = False  # Will update the files/activity log.
    version.addon.update_status()
    return redirect(addon.get_dev_url('versions'))


def check_validation_override(request, form, addon, version):
    if (
        version
        and form.cleaned_data.get('admin_override_validation')
        and acl.action_allowed_for(request.user, amo.permissions.REVIEWS_ADMIN)
    ):
        helper = ReviewHelper(addon=addon, version=version, user=request.user)
        helper.set_data(
            {
                'comments': gettext(
                    'This upload has failed validation, and may '
                    'lack complete validation results. Please '
                    'take due care when reviewing it.'
                ),
            }
        )
        helper.handler.process_comment()
        flag = 'auto_approval_disabled_until_next_approval'
        if version.channel == amo.CHANNEL_UNLISTED:
            flag = 'auto_approval_disabled_until_next_approval_unlisted'
        AddonReviewerFlags.objects.update_or_create(addon=addon, defaults={flag: True})


@dev_required
def version_list(request, addon_id, addon):
    unread_count = (
        (
            ActivityLog.objects.all()
            # There are 2 subquery: the one in pending_for_developer() to
            # determine the date that determines whether an activity is pending
            # or not, and then that queryset which is applied for each version.
            # That means the version filtering needs to be applied twice: for
            # both the date threshold (inner subquery, so the version id to
            # refer to is the parent of the parent) and the unread count itself
            # ("regular" subquery so the version id to refer to is just the
            # parent).
            .pending_for_developer(for_version=OuterRef(OuterRef('id')))
            # pending_for_developer() evaluates the queryset it's called from
            # so we have to apply our second filter w/ OuterRef *after* calling
            # it, otherwise OuterRef would point to the wrong parent.
            .filter(versionlog__version=OuterRef('id'))
            .values('id')
        )
        .annotate(count=Func(F('id'), function='COUNT'))
        .values('count')
    )
    qs = (
        addon.versions.all()
        .no_transforms()
        .select_related('blockversion', 'file', 'file__validation')
        .annotate(unread_count=Subquery(unread_count))
        .order_by('-created')
    )
    versions = amo_utils.paginate(request, qs)
    is_admin = acl.action_allowed_for(request.user, amo.permissions.REVIEWS_ADMIN)
    was_rollback_submit = request.method == 'POST' and 'rollback-submit' in request.POST
    rollback_form = forms.RollbackVersionForm(
        request.POST if was_rollback_submit else None, addon=addon
    )
    rejected_log = (
        addon.status == amo.STATUS_REJECTED
        and ActivityLog.objects.filter(
            addonlog__addon=addon, action=amo.LOG.REJECT_LISTING_CONTENT.id
        )
        .order_by('-created')
        .first()
    )
    rejection_review_requested = (
        rejected_log
        and addon.addonapprovalscounter.content_review_status
        == AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.REQUESTED
    )

    if was_rollback_submit and rollback_form.is_valid():
        duplicate_addon_version_for_rollback.delay(
            version_pk=rollback_form.cleaned_data['version'].pk,
            new_version_number=rollback_form.cleaned_data['new_version_string'],
            user_pk=request.user.pk,
            notes=rollback_form.cleaned_data['release_notes'],
        )
        messages.success(
            request,
            gettext("Rollback submitted. You'll be notified when it's approved"),
        )
        # we posted to #version-rollback so an error reopens the form, but we want
        # success to go to the list proper, so append `#` to clear the fragment.
        return redirect(addon.get_dev_url('versions') + '#')

    data = {
        'addon': addon,
        'can_request_review': addon.can_request_review(),
        'can_rollback': rollback_form.can_rollback(),
        'can_submit': addon.status != amo.STATUS_DISABLED,
        'comments_maxlength': CommentLog._meta.get_field('comments').max_length,
        'latest_approved_unlisted_version_number': rollback_form.can_rollback()
        and addon.versions.filter(
            channel=amo.CHANNEL_UNLISTED, file__status=amo.STATUS_APPROVED
        )
        .values_list('version', flat=True)
        .first(),
        'is_admin': is_admin,
        'rejection_manual_reasoning_text': rejected_log.details.get('comments', '')
        if rejected_log
        else '',
        'rejection_policy_texts': rejected_log.details.get('policy_texts', [])
        if rejected_log
        else [],
        'rejection_review_requested': rejection_review_requested,
        'rollback_form': rollback_form,
        'session_id': request.session.session_key,
        'versions': versions,
    }
    return TemplateResponse(request, 'devhub/versions/list.html', context=data)


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
    reviews = qs.annotate(review_count=Count('ratings')).values(
        'id', 'version', 'review_count'
    )
    data = {v['id']: v for v in reviews}
    for id_ in qs.values_list('id', flat=True):
        # For backwards compatibility
        data[id_]['files'] = 1
        data[id_]['reviews'] = data[id_].pop('review_count')
    return data


@two_factor_auth_required
@login_required
def submit_addon(request):
    return render_agreement(
        request=request,
        template='devhub/addons/submit/start.html',
        next_step='devhub.submit.distribution',
    )


@login_required
def submit_theme(request):
    return render_agreement(
        request=request,
        template='devhub/addons/submit/start.html',
        next_step='devhub.submit.theme.distribution',
    )


@dev_required
@two_factor_auth_required_if_non_theme
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
    elif 'channel' in request.GET and (not addon or not addon.disabled_by_user):
        data = request.GET
    else:
        data = None
    form = forms.DistributionChoiceForm(data, addon=addon)

    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        args = [addon.slug] if addon else []
        args.append(data['channel'])
        return redirect(next_view, *args)
    return TemplateResponse(
        request,
        'devhub/addons/submit/distribute.html',
        context={
            'addon': addon,
            'distribution_form': form,
            'submit_notification_warning': get_config(
                amo.config_keys.SUBMIT_NOTIFICATION_WARNING
            ),
            'submit_page': 'version' if addon else 'addon',
        },
    )


@two_factor_auth_required
@login_required
def submit_addon_distribution(request):
    if not RestrictionChecker(request=request).is_submission_allowed():
        return redirect('devhub.submit.agreement')
    return _submit_distribution(request, None, 'devhub.submit.upload')


@login_required
def submit_theme_distribution(request):
    if not RestrictionChecker(request=request).is_submission_allowed():
        return redirect('devhub.submit.theme.agreement')
    return _submit_distribution(request, None, 'devhub.submit.theme.upload')


@dev_required(submitting=True)
@two_factor_auth_required_if_non_theme
def submit_version_distribution(request, addon_id, addon):
    if not RestrictionChecker(request=request).is_submission_allowed():
        return redirect('devhub.submit.version.agreement', addon.slug)
    return _submit_distribution(request, addon, 'devhub.submit.version.upload')


WIZARD_COLOR_FIELDS = [
    (
        'frame',
        _('Header area background'),
        _(
            'The color of the header area background, displayed in the part of '
            'the header not covered or visible through the header image. Manifest '
            'field:  frame.'
        ),
        'rgba(229,230,232,1)',
    ),
    (
        'tab_background_text',
        _('Header area text and icons'),
        _(
            'The color of the text and icons in the header area, except the '
            'active tab. Manifest field:  tab_background_text.'
        ),
        'rgba(0,0,0,1)',
    ),
    (
        'toolbar',
        _('Toolbar area background'),
        _(
            'The background color for the navigation bar, the bookmarks bar, and '
            'the active tab.  Manifest field:  toolbar.'
        ),
        False,
    ),
    (
        'bookmark_text',
        _('Toolbar area text and icons'),
        _(
            'The color of the text and icons in the toolbar and the active tab. '
            'Manifest field:  bookmark_text.'
        ),
        False,
    ),
    (
        'toolbar_field',
        _('Toolbar field area background'),
        _(
            'The background color for fields in the toolbar, such as the URL bar. '
            'Manifest field:  toolbar_field.'
        ),
        False,
    ),
    (
        'toolbar_field_text',
        _('Toolbar field area text'),
        _(
            'The color of text in fields in the toolbar, such as the URL bar. '
            'Manifest field:  toolbar_field_text.'
        ),
        False,
    ),
    ('', '', '', False),  # empty field
    (
        'tab_line',
        _('Tab highlight'),
        _(
            'The highlight color of the active tab. Implemented as a border around the '
            'tab on Firefox 89+ and a line above the tab on older Firefoxes. '
            'Manifest field:  tab_line.'
        ),
        False,
    ),
]


@transaction.atomic
def _submit_upload(
    request,
    addon,
    channel,
    next_view,
    wizard=False,
    theme_specific=False,
    include_recaptcha=False,
):
    """If this is a new addon upload `addon` will be None.

    next_view is the view that will be redirected to.
    """
    if (
        addon
        and channel == amo.CHANNEL_LISTED
        and not addon.can_submit_listed_versions()
    ):
        # Listed versions can not be submitted while the add-on is set to
        # "invisible" (disabled_by_user) or had its listing rejected.
        return redirect('devhub.submit.version.distribution', addon.slug)
    form = forms.NewUploadForm(
        request.POST or None,
        request.FILES or None,
        addon=addon,
        request=request,
        include_recaptcha=include_recaptcha,
    )
    if wizard or (addon and addon.type == amo.ADDON_STATICTHEME):
        # If using the wizard or submitting a new version of a theme, we can
        # force theme_specific to be True. If somehow the developer is not
        # uploading a theme, validation will reject it just like if they had
        # tried to use the theme submission flow for an entirely new add-on.
        theme_specific = True
    form.fields['theme_specific'].initial = theme_specific
    channel_text = amo.CHANNEL_CHOICES_API[channel]
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data

        if addon:
            version = Version.from_upload(
                upload=data['upload'],
                addon=addon,
                channel=channel,
                selected_apps=data['compatible_apps'],
                parsed_data=data['parsed_data'],
                client_info=request.META.get('HTTP_USER_AGENT'),
            )
            url_args = [addon.slug, version.id]
            statsd.incr(f'devhub.submission.version.{channel_text}')
        else:
            addon = Addon.from_upload(
                upload=data['upload'],
                channel=channel,
                selected_apps=data['compatible_apps'],
                parsed_data=data['parsed_data'],
                client_info=request.META.get('HTTP_USER_AGENT'),
            )
            version = addon.find_latest_version(channel=channel)
            url_args = [addon.slug, channel_text]
            statsd.incr(f'devhub.submission.addon.{channel_text}')

        check_validation_override(request, form, addon, version)
        addon.update_status()
        return redirect(next_view, *url_args)
    is_admin = acl.action_allowed_for(request.user, amo.permissions.REVIEWS_ADMIN)
    if addon:
        channel_choice_text = (
            forms.DistributionChoiceForm().LISTED_LABEL
            if channel == amo.CHANNEL_LISTED
            else forms.DistributionChoiceForm().UNLISTED_LABEL
        )
    else:
        channel_choice_text = ''  # We only need this for Version upload.

    submit_page = 'version' if addon else 'addon'
    template = (
        'devhub/addons/submit/upload.html'
        if not wizard
        else 'devhub/addons/submit/wizard.html'
    )
    existing_properties = (
        extract_theme_properties(addon, channel) if wizard and addon else {}
    )
    unsupported_properties = (
        wizard_unsupported_properties(
            existing_properties,
            [field for field, _, _, _ in WIZARD_COLOR_FIELDS if field],
        )
        if existing_properties
        else []
    )
    flag = waffle.get_waffle_flag_model().get('enable-submissions')
    warning = gettext('Add-on uploads are temporarily unavailable') + (
        ': ' + flag.note if getattr(flag, 'note', None) else '.'
    )
    submit_notification_warning = (
        warning
        if not flag.is_active(request)
        else get_config(amo.config_keys.SUBMIT_NOTIFICATION_WARNING)
    )
    if not submit_notification_warning and addon:
        # If we're not showing the generic submit notification warning, show
        # one specific to pre review if the developer would be affected because
        # of its promoted group.
        promoted_group = addon.promoted_groups(currently_approved=False)
        if (
            channel == amo.CHANNEL_LISTED and any(promoted_group.listed_pre_review)
        ) or (
            channel == amo.CHANNEL_UNLISTED and any(promoted_group.unlisted_pre_review)
        ):
            submit_notification_warning = get_config(
                amo.config_keys.SUBMIT_NOTIFICATION_WARNING_PRE_REVIEW
            )
    if addon and addon.type == amo.ADDON_STATICTHEME:
        wizard_url = reverse(
            'devhub.submit.version.wizard', args=[addon.slug, channel_text]
        )
    elif not addon and theme_specific:
        wizard_url = reverse('devhub.submit.wizard', args=[channel_text])
    else:
        wizard_url = None
    return TemplateResponse(
        request,
        template,
        context={
            'addon': addon,
            'channel': channel,
            'channel_choice_text': channel_choice_text,
            'colors': WIZARD_COLOR_FIELDS,
            'existing_properties': existing_properties,
            'is_admin': is_admin,
            'new_addon_form': form,
            'submit_notification_warning': submit_notification_warning,
            'submit_page': submit_page,
            'theme_specific': theme_specific,
            'unsupported_properties': unsupported_properties,
            'version_number': get_next_version_number(addon) if wizard else None,
            'wizard_url': wizard_url,
            'max_upload_size': settings.MAX_UPLOAD_SIZE,
            'submissions_enabled': flag.is_active(request),
        },
    )


@two_factor_auth_required
@login_required
def submit_addon_upload(request, channel):
    if not RestrictionChecker(request=request).is_submission_allowed():
        return redirect('devhub.submit.agreement')
    channel_id = amo.CHANNEL_CHOICES_LOOKUP[channel]
    return _submit_upload(
        request, None, channel_id, 'devhub.submit.source', include_recaptcha=True
    )


@login_required
def submit_theme_upload(request, channel):
    if not RestrictionChecker(request=request).is_submission_allowed():
        return redirect('devhub.submit.theme.agreement')
    channel_id = amo.CHANNEL_CHOICES_LOOKUP[channel]
    return _submit_upload(
        request, None, channel_id, 'devhub.submit.source', theme_specific=True
    )


@dev_required(submitting=True)
@two_factor_auth_required_if_non_theme
@no_admin_disabled
def submit_version_upload(request, addon_id, addon, channel):
    if not RestrictionChecker(request=request).is_submission_allowed():
        return redirect('devhub.submit.version.agreement', addon.slug)
    channel_id = amo.CHANNEL_CHOICES_LOOKUP[channel]
    return _submit_upload(request, addon, channel_id, 'devhub.submit.version.source')


@dev_required(submitting=True)
@two_factor_auth_required_if_non_theme
@no_admin_disabled
def submit_version_auto(request, addon_id, addon):
    if not RestrictionChecker(request=request).is_submission_allowed():
        return redirect('devhub.submit.version.agreement', addon.slug)
    # Choose the channel we need from the last upload, unless that channel
    # would be listed and addon is set to "Invisible".
    last_version = addon.find_latest_version(None, exclude=())
    if not last_version or (
        last_version.channel == amo.CHANNEL_LISTED and addon.disabled_by_user
    ):
        return redirect('devhub.submit.version.distribution', addon.slug)
    channel = last_version.channel
    return _submit_upload(request, addon, channel, 'devhub.submit.version.source')


@login_required
def submit_addon_theme_wizard(request, channel):
    if not RestrictionChecker(request=request).is_submission_allowed():
        return redirect('devhub.submit.agreement')
    channel_id = amo.CHANNEL_CHOICES_LOOKUP[channel]
    return _submit_upload(
        request, None, channel_id, 'devhub.submit.source', wizard=True
    )


@dev_required
@no_admin_disabled
def submit_version_theme_wizard(request, addon_id, addon, channel):
    if not RestrictionChecker(request=request).is_submission_allowed():
        return redirect('devhub.submit.version.agreement', addon.slug)
    channel_id = amo.CHANNEL_CHOICES_LOOKUP[channel]
    return _submit_upload(
        request, addon, channel_id, 'devhub.submit.version.source', wizard=True
    )


def _submit_source(request, addon, version, submit_page, next_view):
    posting = request.method == 'POST'
    redirect_args = (
        [addon.slug, version.pk]
        if version and submit_page == 'version'
        else [addon.slug]
    )
    if addon.type != amo.ADDON_EXTENSION:
        return redirect(next_view, *redirect_args)
    source_form = forms.SourceForm(
        request.POST or None,
        request.FILES or None,
        instance=version,
        request=request,
    )
    has_source = source_form.data.get('has_source') == 'yes'
    if has_source and posting:
        timer = StopWatch('devhub.views._submit_source.')
        timer.start()
        log.info(
            '_submit_source, form populated, addon.slug: %s, version.pk: %s',
            addon.slug,
            version.pk,
        )
        timer.log_interval('1.form_populated')

    if request.method == 'POST' and source_form.is_valid():
        if has_source:
            log.info(
                '_submit_source, form validated, addon.slug: %s, version.pk: %s',
                addon.slug,
                version.pk,
            )
            timer.log_interval('2.form_validated')
        if source_form.cleaned_data.get('source'):
            source_form.save()
            version.flag_if_sources_were_provided(request.user)
            log.info(
                '_submit_source, form saved, addon.slug: %s, version.pk: %s',
                addon.slug,
                version.pk,
            )
            timer.log_interval('3.form_saved')

        result = redirect(next_view, *redirect_args)
        if has_source:
            log.info(
                '_submit_source, redirecting to next view, '
                + 'addon.slug: %s, version.pk: %s',
                addon.slug,
                version.pk,
            )
            timer.log_interval('4.redirecting_to_next_view')
        return result
    context = {
        'source_form': source_form,
        'addon': addon,
        'version': version,
        'submit_page': submit_page,
        'max_upload_size': settings.MAX_UPLOAD_SIZE,
    }
    if has_source and posting:
        log.info(
            '_submit_source, validation failed, re-displaying the template, '
            + 'addon.slug: %s, version.pk: %s',
            addon.slug,
            version.pk,
        )
        timer.log_interval('5.validation_failed_re-displaying_the_template')
    return TemplateResponse(
        request, 'devhub/addons/submit/source.html', context=context
    )


@dev_required(submitting=True)
def submit_addon_source(request, addon_id, addon, channel):
    channel = amo.CHANNEL_CHOICES_LOOKUP[channel]
    version = addon.find_latest_version(channel=channel)
    return _submit_source(request, addon, version, 'addon', 'devhub.submit.details')


@dev_required(submitting=True)
def submit_version_source(request, addon_id, addon, version_id):
    version = get_object_or_404(addon.versions.all(), id=version_id)
    return _submit_source(
        request, addon, version, 'version', 'devhub.submit.version.details'
    )


@require_submissions_enabled
def _submit_details(request, addon, version):
    static_theme = addon.type == amo.ADDON_STATICTHEME
    if version:
        skip_details_step = version.channel == amo.CHANNEL_UNLISTED or (
            static_theme and addon.has_complete_metadata()
        )
        if skip_details_step:
            # Nothing to do here.
            return redirect('devhub.submit.version.finish', addon.slug, version.pk)
        latest_version = version
    else:
        # Figure out the latest version early in order to pass the same
        # instance to each form that needs it (otherwise they might overwrite
        # each other).
        latest_version = addon.find_latest_version(channel=amo.CHANNEL_LISTED)
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
                post_data,
                instance=addon,
                request=request,
                version=version,
                should_auto_crop=True,
            )
        else:
            describe_form = forms.DescribeForm(
                post_data, instance=addon, request=request, version=version
            )
        cat_form = forms.CategoryForm(post_data, addon=addon, request=request)
        policy_form = forms.PolicyForm(post_data, addon=addon)
        license_form = forms.LicenseForm(
            post_data, version=latest_version, prefix='license'
        )
        context.update(license_form.get_context())
        context.update(
            describe_form=describe_form,
            cat_form=cat_form,
            policy_form=policy_form,
        )
        forms_list.extend(
            [describe_form, cat_form, policy_form, context['license_form']]
        )
    if not static_theme:
        # Static themes don't need this form
        reviewer_form = forms.VersionForm(post_data, instance=latest_version)
        context.update(reviewer_form=reviewer_form)
        forms_list.append(reviewer_form)

    if request.method == 'POST' and all(form.is_valid() for form in forms_list):
        if show_all_fields:
            addon = describe_form.save()
            cat_form.save()
            policy_form.save()
            license_form.save(log=False)
            if not static_theme:
                reviewer_form.save()
            addon.update_status()
        elif not static_theme:
            reviewer_form.save()

        if not version:
            return redirect('devhub.submit.finish', addon.slug)
        else:
            return redirect('devhub.submit.version.finish', addon.slug, version.id)
    template = 'devhub/addons/submit/%s' % (
        'describe.html' if show_all_fields else 'describe_minimal.html'
    )
    return TemplateResponse(request, template, context=context)


@dev_required(submitting=True)
def submit_addon_details(request, addon_id, addon):
    return _submit_details(request, addon, None)


@dev_required(submitting=True)
def submit_version_details(request, addon_id, addon, version_id):
    version = get_object_or_404(addon.versions.all(), id=version_id)
    return _submit_details(request, addon, version)


@require_submissions_enabled
def _submit_finish(request, addon, version):
    uploaded_version = version or addon.versions.latest()

    submit_page = 'version' if version else 'addon'
    return TemplateResponse(
        request,
        'devhub/addons/submit/done.html',
        context={
            'addon': addon,
            'uploaded_version': uploaded_version,
            'submit_page': submit_page,
            'preview': uploaded_version.previews.first(),
        },
    )


@dev_required(submitting=True)
def submit_addon_finish(request, addon_id, addon):
    # Bounce to the details step if incomplete
    if not addon.has_complete_metadata() and addon.find_latest_version(
        channel=amo.CHANNEL_LISTED
    ):
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

    latest_version = addon.find_latest_version(amo.CHANNEL_LISTED, exclude=())
    if latest_version:
        if latest_version.file.status == amo.STATUS_DISABLED:
            latest_version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        # Clear the due date so it gets set again in Addon.watch_status if necessary.
        latest_version.reset_due_date()
    if addon.has_complete_metadata():
        addon.update_status()
        messages.success(request, gettext('Review requested.'))
    else:
        messages.success(request, _('You must provide further details to proceed.'))
    ActivityLog.objects.create(amo.LOG.CHANGE_STATUS, addon, addon.status)
    return redirect(addon.get_dev_url('versions'))


def docs(request, doc_name=None):
    def get_url(base, doc_path=None):
        base_url = urljoin(base, doc_path)
        query = urlencode({'utm_referrer': 'amo'})
        return f'{base_url}?{query}'

    def mdn_url(doc_path):
        return get_url(MDN_BASE, doc_path)

    def ext_url(doc_path):
        return get_url(settings.EXTENSION_WORKSHOP_URL, doc_path)

    mdn_docs = {
        None: mdn_url(''),
        'getting-started': mdn_url(''),
        'reference': mdn_url(''),
        'how-to': mdn_url(''),
        'how-to/getting-started': mdn_url(''),
        'how-to/extension-development': mdn_url('#Extensions'),
        'how-to/other-addons': mdn_url('#Other_types_of_add-ons'),
        'how-to/thunderbird-mobile': mdn_url('#Application-specific'),
        'how-to/theme-development': mdn_url('#Themes'),
        'themes': mdn_url('/Themes/Background'),
        'themes/faq': mdn_url('/Themes/Background/FAQ'),
        'policies': ext_url('/documentation/publish/add-on-policies'),
        'policies/faq': ext_url('/documentation/publish/add-on-policies-faq'),
        'policies/agreement': ext_url(
            '/documentation/publish/firefox-add-on-distribution-agreement'
        ),
    }

    if doc_name in mdn_docs:
        return redirect(mdn_docs[doc_name], permanent=True)

    raise http.Http404()


@login_required
def developer_agreement(request):
    return render_agreement(
        request=request,
        template='devhub/agreement.html',
        next_step=request.GET.get('to'),
    )


def render_agreement(request, template, next_step, **extra_context):
    form = forms.AgreementForm(
        request.POST if request.method == 'POST' else None, request=request
    )
    if not is_safe_url(next_step, request):
        next_step = reverse('devhub.index')
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
    elif not RestrictionChecker(request=request).is_submission_allowed():
        # Developer has either posted an invalid form or just landed on the
        # page but haven't read the agreement yet, or isn't allowed to submit
        # for some other reason (denied ip/email): show the form (with
        # potential errors highlighted)
        context = {
            'agreement_form': form,
        }
        context.update(extra_context)
        return TemplateResponse(request, template, context=context)
    else:
        # The developer has already read the agreement, we should just redirect
        # to the next step.
        response = redirect(next_step)
        return response


@two_factor_auth_required
@login_required
@transaction.atomic
def api_key(request):
    if not RestrictionChecker(request=request).is_submission_allowed():
        return redirect(
            '%s%s%s'
            % (reverse('devhub.developer_agreement'), '?to=', quote(request.path))
        )

    form = forms.APIKeyForm(
        request.POST if request.method == 'POST' else None,
        request=request,
    )

    if request.method == 'POST' and form.is_valid():
        result = form.save()

        if result.get('credentials_revoked'):
            log.info(
                f'revoking JWT key for user: {request.user.id}, {form.credentials}'
            )
            send_key_revoked_email(request.user.email, form.credentials.key)

            # The user can revoke or regenerate.
            # If not regenerating, skip the rest of the logic.
            if not result.get('credentials_generated'):
                msg = gettext(
                    'Your old credentials were revoked and are no longer valid.'
                )
                messages.success(request, msg)
                return redirect(reverse('devhub.api_key'))

        if result.get('credentials_generated'):
            new_credentials = form.credentials
            log.info(f'new JWT key created: {new_credentials}')
            send_key_change_email(request.user.email, new_credentials.key)

        if result.get('confirmation_created'):
            form.confirmation.send_confirmation_email()

        return redirect(reverse('devhub.api_key'))

    if form.credentials is not None:
        messages.error(
            request,
            _(
                'Keep your API keys secret and never share them with anyone, '
                'including Mozilla contributors.'
            ),
        )

    context_data = {
        'title': gettext('Manage API Keys'),
        'form': form,
    }

    return TemplateResponse(request, 'devhub/api/key.html', context=context_data)


def send_key_change_email(to_email, key):
    template = loader.get_template('devhub/emails/new-key-email.ltxt')
    url = absolutify(reverse('devhub.api_key'))
    send_mail(
        gettext('New API key created'),
        template.render({'key': key, 'url': url}),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[to_email],
    )


def send_key_revoked_email(to_email, key):
    template = loader.get_template('devhub/emails/revoked-key-email.ltxt')
    url = absolutify(reverse('devhub.api_key'))
    send_mail(
        gettext('API key revoked'),
        template.render({'key': key, 'url': url}),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[to_email],
    )


@dev_required
@json_view
def theme_background_image(request, addon_id, addon, channel):
    channel_id = amo.CHANNEL_CHOICES_LOOKUP[channel]
    version = addon.find_latest_version(channel_id)
    return version.get_background_images_encoded(header_only=True) if version else {}


def logout(request):
    user = request.user
    if not user.is_anonymous:
        log.info('User (%s) logged out' % user)

    if 'to' in request.GET and not is_safe_url(request.GET['to'], request):
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


VERIFY_EMAIL_STATE = {
    'email_verified': 'email_verified',
    'email_suppressed': 'email_suppressed',
    'verification_expired': 'verification_expired',
    'verification_pending': 'verification_pending',
    'verification_timedout': 'verification_timedout',
    'confirmation_pending': 'confirmation_pending',
    'confirmation_invalid': 'confirmation_invalid',
}

RENDER_BUTTON_STATES = [
    VERIFY_EMAIL_STATE['email_suppressed'],
    VERIFY_EMAIL_STATE['verification_expired'],
    VERIFY_EMAIL_STATE['verification_timedout'],
    VERIFY_EMAIL_STATE['confirmation_invalid'],
]


def get_button_text(state):
    if state == VERIFY_EMAIL_STATE['email_suppressed']:
        return gettext('Verify email')

    return gettext('Send another email')


@login_required
def email_verification(request):
    data = {'state': None}
    email_verification = request.user.email_verification
    suppressed_email = request.user.suppressed_email

    if not waffle.switch_is_active('suppressed-email'):
        return redirect('devhub.addons')

    if request.method == 'POST':
        if email_verification:
            email_verification.delete()

        if suppressed_email:
            email_verification = SuppressedEmailVerification.objects.create(
                suppressed_email=suppressed_email
            )
            send_suppressed_email_confirmation.delay(email_verification.id)

        return redirect('devhub.email_verification')

    if email_verification:
        data['render_table'] = True
        data['found_emails'] = check_suppressed_email_confirmation(email_verification)
        if email_verification.is_expired:
            data['state'] = VERIFY_EMAIL_STATE['verification_expired']
        elif code := request.GET.get('code'):
            if code == email_verification.confirmation_code:
                suppressed_email.delete()
                send_mail_jinja(
                    gettext('Your email has been verified'),
                    'devhub/emails/verify-email-completed.ltxt',
                    {},
                    recipient_list=[request.user.email],
                )
                return redirect('devhub.email_verification')
            else:
                data['state'] = VERIFY_EMAIL_STATE['confirmation_invalid']
        elif email_verification.is_timedout:
            data['state'] = VERIFY_EMAIL_STATE['verification_timedout']
        else:
            if (
                email_verification.reload().status
                == SuppressedEmailVerification.STATUS_CHOICES.DELIVERED
            ):
                data['state'] = VERIFY_EMAIL_STATE['confirmation_pending']
                data['render_table'] = False
            else:
                data['state'] = VERIFY_EMAIL_STATE['verification_pending']

    elif suppressed_email:
        data['state'] = VERIFY_EMAIL_STATE['email_suppressed']
    else:
        data['state'] = VERIFY_EMAIL_STATE['email_verified']

    if data['state'] is None:
        raise Exception('Invalid view must result in assigned state')

    if data['state'] in RENDER_BUTTON_STATES:
        data['render_button'] = True
        data['button_text'] = get_button_text(data['state'])

    return TemplateResponse(request, 'devhub/verify_email.html', context=data)


@post_required
@login_required
def survey_response(request, survey_id):
    try:
        SurveyResponse.objects.update_or_create(
            user=request.user,
            survey_id=survey_id,
        )
    except IntegrityError:
        return http.HttpResponse(status=500)
    return http.HttpResponse(status=201)
