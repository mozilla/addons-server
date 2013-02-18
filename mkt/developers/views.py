import json
import os
import sys
import traceback

from django import http
from django import forms as django_forms
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_view_exempt

import commonware.log
import jingo
from session_csrf import anonymous_csrf, anonymous_csrf_exempt
from tower import ugettext as _, ugettext_lazy as _lazy
import waffle
from waffle.decorators import waffle_switch

import amo
import amo.utils
from access import acl
from addons import forms as addon_forms
from addons.decorators import addon_view
from addons.models import Addon, AddonUser
from addons.views import BaseFilter
from amo import messages
from amo.decorators import (any_permission_required, json_view, login_required,
                            post_required)
from amo.urlresolvers import reverse
from amo.utils import escape_all
from devhub.forms import VersionForm
from devhub.models import AppLog
from files.models import File, FileUpload
from files.utils import parse_addon
from market.models import Refund
from stats.models import Contribution
from translations.models import delete_translation
from users.models import UserProfile
from users.views import _login
from versions.models import Version

from mkt.api.models import Access, generate
from mkt.constants import APP_IMAGE_SIZES
from mkt.developers.decorators import dev_required
from mkt.developers.forms import (AppFormBasic, AppFormDetails, AppFormMedia,
                                  AppFormSupport, AppFormTechnical,
                                  CategoryForm, ImageAssetFormSet,
                                  NewPackagedAppForm, PreviewFormSet,
                                  TransactionFilterForm, trap_duplicate)
from mkt.developers.utils import check_upload
from mkt.submit.forms import NewWebappVersionForm
from mkt.webapps.tasks import update_manifests, _update_manifest
from mkt.webapps.models import Webapp

from . import forms, tasks

log = commonware.log.getLogger('z.devhub')


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
            ('created', _lazy(u'Created')))


def addon_listing(request, default='name', webapp=False):
    """Set up the queryset and filtering for addon listing for Dashboard."""
    Filter = AppFilter if webapp else AddonFilter
    addons = UserProfile.objects.get(pk=request.user.id).addons
    if webapp:
        qs = Webapp.objects.filter(id__in=addons.filter(type=amo.ADDON_WEBAPP))
        model = Webapp
    else:
        qs = addons.exclude(type=amo.ADDON_WEBAPP)
        model = Addon
    filter = Filter(request, qs, 'sort', default, model=model)
    return filter.qs, filter


@anonymous_csrf
def login(request, template=None):
    return _login(request, template='developers/login.html')


def home(request):
    return index(request)


@login_required
def index(request):
    # This is a temporary redirect.
    return redirect('mkt.developers.apps')


@login_required
def dashboard(request, webapp=False):
    addons, filter = addon_listing(request, webapp=webapp)
    addons = amo.utils.paginate(request, addons, per_page=10)
    data = dict(addons=addons, sorting=filter.field, filter=filter,
                sort_opts=filter.opts, webapp=webapp)
    return jingo.render(request, 'developers/apps/dashboard.html', data)


@dev_required(webapp=True)
def edit(request, addon_id, addon, webapp=False):
    data = {
        'page': 'edit',
        'addon': addon,
        'webapp': webapp,
        'valid_slug': addon.app_slug,
        'image_sizes': APP_IMAGE_SIZES,
        'tags': addon.tags.not_blacklisted().values_list('tag_text',
                                                         flat=True),
        'previews': addon.get_previews(),
    }
    if acl.action_allowed(request, 'Apps', 'Configure'):
        data['admin_settings_form'] = forms.AdminSettingsForm(instance=addon)
    return jingo.render(request, 'developers/apps/edit.html', data)


@dev_required(owner_for_post=True, webapp=True)
def delete(request, addon_id, addon, webapp=False):
    # Database deletes only allowed for free or incomplete addons.
    if not addon.can_be_deleted():
        msg = _('Paid apps cannot be deleted. Disable this app instead.')
        messages.error(request, msg)
        return redirect(addon.get_dev_url('versions'))

    # TODO: This short circuits the delete form which checks the password. When
    # BrowserID adds re-auth support, update the form to check with BrowserID
    # and remove the short circuit.
    form = forms.DeleteForm(request)
    if True or form.is_valid():
        addon.delete('Removed via devhub')
        messages.success(request, _('App deleted.'))
        # Preserve query-string parameters if we were directed from Dashboard.
        return redirect(request.GET.get('to') or
                        reverse('mkt.developers.apps'))
    else:
        msg = _('Password was incorrect.  App was not deleted.')
        messages.error(request, msg)
        return redirect(addon.get_dev_url('versions'))


@dev_required
def enable(request, addon_id, addon):
    addon.update(disabled_by_user=False)
    amo.log(amo.LOG.USER_ENABLE, addon)
    return redirect(addon.get_dev_url('versions'))


@dev_required
@post_required
def disable(request, addon_id, addon):
    addon.update(disabled_by_user=True)
    amo.log(amo.LOG.USER_DISABLE, addon)
    return redirect(addon.get_dev_url('versions'))


@dev_required
@post_required
def publicise(request, addon_id, addon):
    if addon.status == amo.STATUS_PUBLIC_WAITING:
        addon.update(status=amo.STATUS_PUBLIC)
        File.objects.filter(
            version__addon=addon, status=amo.STATUS_PUBLIC_WAITING).update(
                status=amo.STATUS_PUBLIC)
        amo.log(amo.LOG.CHANGE_STATUS, addon.get_status_display(), addon)
        # Call update_version, so various other bits of data update.
        addon.update_version()
        # Call to update names if they changed.
        addon.update_name_from_package_manifest()
    return redirect(addon.get_dev_url('versions'))


@dev_required(webapp=True)
def status(request, addon_id, addon, webapp=False):
    form = forms.AppAppealForm(request.POST, product=addon)
    upload_form = NewWebappVersionForm(request.POST or None, is_packaged=True,
                                       addon=addon)

    if request.method == 'POST':
        if 'resubmit-app' in request.POST and form.is_valid():
            form.save()
            messages.success(request, _('App successfully resubmitted.'))
            return redirect(addon.get_dev_url('versions'))

        elif 'upload-version' in request.POST and upload_form.is_valid():
            ver = Version.from_upload(upload_form.cleaned_data['upload'],
                                      addon, [amo.PLATFORM_ALL])
            messages.success(request, _('New version successfully added.'))
            log.info('[Webapp:%s] New version created id=%s from upload: %s'
                     % (addon, ver.pk, upload_form.cleaned_data['upload']))
            return redirect(addon.get_dev_url('versions.edit', args=[ver.pk]))

    ctx = {'addon': addon, 'webapp': webapp, 'form': form,
           'upload_form': upload_form}

    # Used in the delete version modal.
    if addon.is_packaged:
        versions = addon.versions.values('id', 'version')
        version_strings = dict((v['id'], v) for v in versions)
        version_strings['num'] = len(versions)
        ctx['version_strings'] = json.dumps(version_strings)

    if addon.status == amo.STATUS_REJECTED:
        try:
            entry = (AppLog.objects
                     .filter(addon=addon,
                             activity_log__action=amo.LOG.REJECT_VERSION.id)
                     .order_by('-created'))[0]
        except IndexError:
            entry = None
        # This contains the rejection reason and timestamp.
        ctx['rejection'] = entry and entry.activity_log

    return jingo.render(request, 'developers/apps/status.html', ctx)


@dev_required
def version_edit(request, addon_id, addon, version_id):
    version = get_object_or_404(Version, pk=version_id, addon=addon)
    form = VersionForm(request.POST or None, instance=version)

    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, _('Version successfully edited.'))
        return redirect(addon.get_dev_url('versions'))

    return jingo.render(request, 'developers/apps/version_edit.html', {
        'addon': addon, 'version': version, 'form': form})


@dev_required
@post_required
@transaction.commit_on_success
def version_delete(request, addon_id, addon):
    version_id = request.POST.get('version_id')
    version = get_object_or_404(Version, pk=version_id, addon=addon)
    if version.all_files[0].status == amo.STATUS_BLOCKED:
        raise PermissionDenied
    version.delete()
    messages.success(request,
                     _('Version "{0}" deleted.').format(version.version))
    return redirect(addon.get_dev_url('versions'))


@dev_required(owner_for_post=True, webapp=True)
def ownership(request, addon_id, addon, webapp=False):
    # Authors.
    qs = AddonUser.objects.filter(addon=addon).order_by('position')
    user_form = forms.AuthorFormSet(request.POST or None, queryset=qs)

    if request.method == 'POST' and user_form.is_valid():
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

        messages.success(request, _('Changes successfully saved.'))

        return redirect(addon.get_dev_url('owner'))

    ctx = dict(addon=addon, webapp=webapp, user_form=user_form)
    return jingo.render(request, 'developers/apps/owner.html', ctx)


@waffle_switch('allow-refund')
@dev_required(support=True, webapp=True)
def refunds(request, addon_id, addon, webapp=False):
    ctx = {'addon': addon, 'webapp': webapp}
    queues = {
        'pending': Refund.objects.pending(addon).order_by('requested'),
        'approved': Refund.objects.approved(addon).order_by('-requested'),
        'instant': Refund.objects.instant(addon).order_by('-requested'),
        'declined': Refund.objects.declined(addon).order_by('-requested'),
        'failed': Refund.objects.failed(addon).order_by('-requested'),
    }
    for status, refunds in queues.iteritems():
        ctx[status] = amo.utils.paginate(request, refunds, per_page=50)
    return jingo.render(request, 'developers/payments/refunds.html', ctx)


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

    return jingo.render(request, 'developers/apps/profile.html',
                        dict(addon=addon, webapp=webapp,
                             profile_form=profile_form))


@anonymous_csrf
def validate_addon(request):
    return jingo.render(request, 'developers/validate_addon.html', {
        'upload_hosted_url':
            reverse('mkt.developers.standalone_hosted_upload'),
        'upload_packaged_url':
            reverse('mkt.developers.standalone_packaged_upload'),
    })


@post_required
def _upload(request, addon_slug=None, is_standalone=False):
    # If there is no user, default to None (saves the file upload as anon).
    form = NewPackagedAppForm(request.POST, request.FILES,
                              user=getattr(request, 'amo_user', None))
    if form.is_valid():
        tasks.validator.delay(form.file_upload.pk)

    if addon_slug:
        return redirect('mkt.developers.upload_detail_for_addon',
                        addon_slug, form.file_upload.pk)
    elif is_standalone:
        return redirect('mkt.developers.standalone_upload_detail',
                        'packaged', form.file_upload.pk)
    else:
        return redirect('mkt.developers.upload_detail',
                        form.file_upload.pk, 'json')


@login_required
def upload_new(*args, **kwargs):
    return _upload(*args, **kwargs)


@anonymous_csrf
def standalone_packaged_upload(request):
    return _upload(request, is_standalone=True)


@dev_required
def upload_for_addon(request, addon_id, addon):
    return _upload(request, addon_slug=addon.slug)


@dev_required
def refresh_manifest(request, addon_id, addon, webapp=False):
    log.info('Manifest %s refreshed for %s' % (addon.manifest_url, addon))
    _update_manifest(addon_id, True, ())
    return http.HttpResponse(status=204)


@post_required
@json_view
def _upload_manifest(request, is_standalone=False):
    form = forms.NewManifestForm(request.POST, is_standalone=is_standalone)
    if (not is_standalone and
        waffle.switch_is_active('webapps-unique-by-domain')):
        # Helpful error if user already submitted the same manifest.
        dup_msg = trap_duplicate(request, request.POST.get('manifest'))
        if dup_msg:
            return {'validation': {'errors': 1, 'success': False,
                    'messages': [{'type': 'error', 'message': dup_msg,
                                  'tier': 1}]}}
    if form.is_valid():
        upload = FileUpload.objects.create()
        tasks.fetch_manifest.delay(form.cleaned_data['manifest'], upload.pk)
        if is_standalone:
            return redirect('mkt.developers.standalone_upload_detail',
                            'hosted', upload.pk)
        else:
            return redirect('mkt.developers.upload_detail', upload.pk, 'json')
    else:
        error_text = _('There was an error with the submission.')
        if 'manifest' in form.errors:
            error_text = ' '.join(form.errors['manifest'])
        error_message = {'type': 'error', 'message': error_text, 'tier': 1}

        v = {'errors': 1, 'success': False, 'messages': [error_message]}
        return make_validation_result(dict(validation=v, error=error_text))


@login_required
def upload_manifest(*args, **kwargs):
    """Wrapper function for `_upload_manifest` so we can keep the
    standalone validator separate from the manifest upload stuff.

    """
    return _upload_manifest(*args, **kwargs)


def standalone_hosted_upload(request):
    return _upload_manifest(request, is_standalone=True)


@json_view
@anonymous_csrf_exempt
def standalone_upload_detail(request, type_, uuid):
    upload = get_object_or_404(FileUpload.uncached, uuid=uuid)
    url = reverse('mkt.developers.standalone_upload_detail',
                  args=[type_, uuid])
    return upload_validation_context(request, upload, url=url)


@dev_required
@json_view
def upload_detail_for_addon(request, addon_id, addon, uuid):
    upload = get_object_or_404(FileUpload.uncached, uuid=uuid)
    return json_upload_detail(request, upload, addon_slug=addon.slug)


def make_validation_result(data):
    """Safe wrapper around JSON dict containing a validation result."""
    if not settings.EXPOSE_VALIDATOR_TRACEBACKS:
        if data['error']:
            # Just expose the message, not the traceback.
            data['error'] = data['error'].strip().split('\n')[-1].strip()
    if data['validation']:
        for msg in data['validation']['messages']:
            for k, v in msg.items():
                msg[k] = escape_all(v)
    return data


@dev_required(allow_editors=True)
def file_validation(request, addon_id, addon, file_id):
    file = get_object_or_404(File, id=file_id)

    v = addon.get_dev_url('json_file_validation', args=[file.id])
    return jingo.render(request, 'developers/validation.html',
                        dict(validate_url=v, filename=file.filename,
                             timestamp=file.created,
                             addon=addon))


@json_view
@csrf_view_exempt
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
            return make_validation_result({'validation': '',
                                           'error': error})
    else:
        v_result = file.validation
    validation = json.loads(v_result.validation)

    return make_validation_result(dict(validation=validation,
                                       error=None))


@json_view
def json_upload_detail(request, upload, addon_slug=None):
    addon = None
    if addon_slug:
        addon = get_object_or_404(Addon, slug=addon_slug)
    result = upload_validation_context(request, upload, addon=addon)
    if result['validation']:
        if result['validation']['errors'] == 0:
            try:
                parse_addon(upload, addon=addon)
            except django_forms.ValidationError, exc:
                m = []
                for msg in exc.messages:
                    # Simulate a validation error so the UI displays it.
                    m.append({'type': 'error', 'message': msg, 'tier': 1})
                v = make_validation_result(dict(error='',
                                                validation=dict(messages=m)))
                return json_view.error(v)
    return result


def upload_validation_context(request, upload, addon_slug=None, addon=None,
                              url=None):
    if addon_slug and not addon:
        addon = get_object_or_404(Addon, slug=addon_slug)
    if not settings.VALIDATE_ADDONS:
        upload.task_error = ''
        upload.is_webapp = True
        upload.validation = json.dumps({'errors': 0, 'messages': [],
                                        'metadata': {}, 'notices': 0,
                                        'warnings': 0})
        upload.save()

    validation = json.loads(upload.validation) if upload.validation else ''
    if not url:
        if addon:
            url = reverse('mkt.developers.upload_detail_for_addon',
                          args=[addon.slug, upload.uuid])
        else:
            url = reverse('mkt.developers.upload_detail',
                          args=[upload.uuid, 'json'])
    report_url = reverse('mkt.developers.upload_detail', args=[upload.uuid])

    return make_validation_result(dict(upload=upload.uuid,
                                       validation=validation,
                                       error=upload.task_error, url=url,
                                       full_report_url=report_url))


def upload_detail(request, uuid, format='html'):
    upload = get_object_or_404(FileUpload.uncached, uuid=uuid)

    if format == 'json' or request.is_ajax():
        return json_upload_detail(request, upload)

    validate_url = reverse('mkt.developers.standalone_upload_detail',
                           args=['hosted', upload.uuid])
    return jingo.render(request, 'developers/validation.html',
                        dict(validate_url=validate_url, filename=upload.name,
                             timestamp=upload.created))


@dev_required(webapp=True, staff=True)
def addons_section(request, addon_id, addon, section, editable=False,
                   webapp=False):
    basic = AppFormBasic if webapp else addon_forms.AddonFormBasic
    models = {'basic': basic,
              'media': AppFormMedia,
              'details': AppFormDetails,
              'support': AppFormSupport,
              'technical': AppFormTechnical,
              'admin': forms.AdminSettingsForm}

    if section not in models:
        raise http.Http404()

    tags = image_assets = previews = restricted_tags = []
    cat_form = None

    if section == 'basic':
        tags = addon.tags.not_blacklisted().values_list('tag_text', flat=True)
        cat_form = CategoryForm(request.POST or None, product=addon,
                                request=request)
        restricted_tags = addon.tags.filter(restricted=True)

    elif section == 'media':
        image_assets = ImageAssetFormSet(
            request.POST or None, prefix='images', app=addon)
        previews = PreviewFormSet(
            request.POST or None, prefix='files',
            queryset=addon.get_previews())

    elif (section == 'admin' and
          not acl.action_allowed(request, 'Apps', 'Configure') and
          not acl.action_allowed(request, 'Apps', 'ViewConfiguration')):
        raise PermissionDenied

    # Get the slug before the form alters it to the form data.
    valid_slug = addon.app_slug
    if editable:
        if request.method == 'POST':

            if (section == 'admin' and
                not acl.action_allowed(request, 'Apps', 'Configure')):
                raise PermissionDenied

            form = models[section](request.POST, request.FILES,
                                   instance=addon, request=request)
            if (form.is_valid()
                and (not previews or previews.is_valid())
                and (not image_assets or image_assets.is_valid())):

                addon = form.save(addon)

                if 'manifest_url' in form.changed_data:
                    addon.update(
                        app_domain=addon.domain_from_url(addon.manifest_url))
                    update_manifests([addon.pk])

                if previews:
                    for preview in previews.forms:
                        preview.save(addon)

                if image_assets:
                    image_assets.save()

                editable = False
                if section == 'media':
                    amo.log(amo.LOG.CHANGE_ICON, addon)
                else:
                    amo.log(amo.LOG.EDIT_PROPERTIES, addon)

                valid_slug = addon.app_slug
            if cat_form:
                if cat_form.is_valid():
                    cat_form.save()
                    addon.save()
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
            'image_sizes': APP_IMAGE_SIZES,
            'cat_form': cat_form,
            'preview_form': previews,
            'image_asset_form': image_assets,
            'valid_slug': valid_slug, }

    return jingo.render(request,
                        'developers/apps/edit/%s.html' % section, data)


@never_cache
@dev_required(skip_submit_check=True)
@json_view
def image_status(request, addon_id, addon, icon_size=64):
    # Default icon needs no checking.
    if not addon.icon_type or addon.icon_type.split('/')[0] == 'icon':
        icons = True
    # Persona icon is handled differently.
    elif addon.type == amo.ADDON_PERSONA:
        icons = True
    else:
        icons = os.path.exists(os.path.join(addon.get_icon_dir(),
                                            '%s-%s.png' %
                                            (addon.id, icon_size)))
    previews = all(os.path.exists(p.thumbnail_path)
                   for p in addon.get_previews())
    return {'overall': icons and previews,
            'icons': icons,
            'previews': previews}


@json_view
def ajax_upload_media(request, upload_type):
    errors = []
    upload_hash = ''

    if 'upload_image' in request.FILES:
        upload_preview = request.FILES['upload_image']
        upload_preview.seek(0)
        content_type = upload_preview.content_type
        errors, upload_hash = check_upload(upload_preview, upload_type,
                                           content_type)

    else:
        errors.append(_('There was an error uploading your preview.'))

    if errors:
        upload_hash = ''

    return {'upload_hash': upload_hash, 'errors': errors}


@dev_required
def upload_media(request, addon_id, addon, upload_type):
    return ajax_upload_media(request, upload_type)


@dev_required
@post_required
def remove_locale(request, addon_id, addon):
    locale = request.POST.get('locale')
    if locale and locale != addon.default_locale:
        addon.remove_locale(locale)
        return http.HttpResponse()
    return http.HttpResponseBadRequest()


def docs(request, doc_name=None, doc_page=None):
    filename = ''

    all_docs = {'policies': ['agreement']}

    if doc_name and doc_name in all_docs:
        filename = '%s.html' % doc_name
        if doc_page and doc_page in all_docs[doc_name]:
            filename = '%s-%s.html' % (doc_name, doc_page)
        else:
            # TODO: Temporary until we have a `policies` docs index.
            filename = None

    if not filename:
        return redirect('ecosystem.landing')

    return jingo.render(request, 'developers/docs/%s' % filename)


@login_required
def terms(request):
    form = forms.DevAgreementForm({'read_dev_agreement': True},
                                  instance=request.amo_user)
    if request.POST and form.is_valid():
        form.save()
        log.info('Dev agreement agreed for user: %s' % request.amo_user.pk)
        messages.success(request, _('Terms of service accepted.'))
    return jingo.render(request, 'developers/terms.html',
                        {'accepted': request.amo_user.read_dev_agreement,
                         'agreement_form': form})


@waffle_switch('create-api-tokens')
@login_required
def api(request):
    try:
        access = Access.objects.get(user=request.user)
    except Access.DoesNotExist:
        access = None

    roles = request.amo_user.groups.filter(name='Admins').exists()
    if roles:
        messages.error(request,
                       _('Users with the admin role cannot use the API.'))

    elif not request.amo_user.read_dev_agreement:
        messages.error(request, _('You must accept the terms of service.'))

    elif request.method == 'POST':
        if 'delete' in request.POST:
            if access:
                access.delete()
                messages.success(request, _('API key deleted.'))

        else:
            if not access:
                key = 'mkt:%s:%s' % (request.amo_user.pk,
                                     request.amo_user.email)
                access = Access.objects.create(key=key, user=request.user,
                                               secret=generate())
            else:
                access.update(secret=generate())
            messages.success(request, _('New API key generated.'))

        return redirect(reverse('mkt.developers.apps.api'))

    return jingo.render(request, 'developers/api.html',
                        {'consumer': access, 'profile': profile,
                         'roles': roles})


@addon_view
@post_required
@any_permission_required([('Admin', '%'),
                          ('Apps', 'Configure')])
def blocklist(request, addon):
    """
    Blocklists the app by creating a new version/file.
    """
    if addon.status != amo.STATUS_BLOCKED:
        addon.create_blocklisted_version()
        messages.success(request, _('Created blocklisted version.'))
    else:
        messages.info(request, _('App already blocklisted.'))

    return redirect(addon.get_dev_url('versions'))


@waffle_switch('view-transactions')
@login_required
def transactions(request):
    form, transactions = _get_transactions(request)
    return jingo.render(
        request, 'developers/transactions.html',
        {'form': form,
         'CONTRIB_TYPES': amo.CONTRIB_TYPES,
         'count': transactions.count(),
         'transactions': amo.utils.paginate(request,
                                            transactions, per_page=50)})


def _get_transactions(request):
    apps = addon_listing(request, webapp=True)[0]
    transactions = Contribution.objects.filter(addon__in=list(apps),
                                               type__in=amo.CONTRIB_TYPES)

    form = TransactionFilterForm(request.GET, apps=apps)
    if form.is_valid():
        transactions = _filter_transactions(transactions, form.cleaned_data)
    return form, transactions


def _filter_transactions(qs, data):
    """Handle search filters and queries for transactions."""
    filter_mapping = {'app': 'addon_id',
                      'transaction_type': 'type',
                      'transaction_id': 'uuid',
                      'date_from': 'created__gte',
                      'date_to': 'created__lte'}
    for form_field, db_field in filter_mapping.iteritems():
        if data.get(form_field):
            try:
                qs = qs.filter(**{db_field: data[form_field]})
            except ValueError:
                continue
    return qs
