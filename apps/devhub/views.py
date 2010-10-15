import functools
import uuid

from django import http
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import trans_real as translation

import commonware.log
import jingo
import path
from tower import ugettext_lazy as _lazy

import amo.utils
from amo.decorators import login_required, post_required
from access import acl
from addons.forms import AddonFormBasic
from addons.models import Addon, AddonUser, AddonLog
from addons.views import BaseFilter
from files.models import FileUpload
from versions.models import License
from . import tasks
from .forms import (AuthorFormSet, LicenseForm, PolicyForm, ProfileForm,
                    CharityForm, ContribForm)

log = commonware.log.getLogger('z.devhub')

# Acceptable extensions.
EXTENSIONS = ('.xpi', '.jar', '.xml')


def dev_required(f):
    """Requires user to be add-on owner or admin"""
    @login_required
    @functools.wraps(f)
    def wrapper(request, addon_id, *args, **kw):
        addon = get_object_or_404(Addon, id=addon_id)
        if acl.check_addon_ownership(request, addon,
                                     require_owner=False):
            return f(request, addon_id, addon, *args, **kw)
        else:
            return http.HttpResponseForbidden()
    return wrapper


def owner_for_post_required(f):
    @functools.wraps(f)
    def wrapper(request, addon_id, addon, *args, **kw):
        is_admin = acl.action_allowed(request, 'Admin', 'EditAnyAddon')
        qs = addon.authors.filter(addonuser__role=amo.AUTHOR_ROLE_OWNER,
                                  user=request.amo_user)
        if request.method == 'POST' and not (is_admin or qs):
            return http.HttpResponseForbidden()
        else:
            return f(request, addon_id, addon, *args, **kw)
    return wrapper


class AddonFilter(BaseFilter):
    opts = (('name', _lazy(u'Name')),
            ('updated', _lazy(u'Updated')),
            ('created', _lazy(u'Created')),
            ('popular', _lazy(u'Downloads')),
            ('rating', _lazy(u'Rating')))


def addon_listing(request, addon_type, default='name'):
    """Set up the queryset and filtering for addon listing for Dashboard."""
    qs = request.amo_user.addons.all()
    filter = AddonFilter(request, qs, 'sort', default)
    return filter.qs, filter


def index(request):
    return jingo.render(request, 'devhub/index.html')


@login_required
def dashboard(request):
    TYPE = amo.ADDON_ANY
    addons, filter = addon_listing(request, TYPE)
    addons = amo.utils.paginate(request, addons, per_page=10)
    return jingo.render(request, 'devhub/addons/dashboard.html',
                        {'addons': addons, 'sorting': filter.field,
                         'sort_opts': filter.opts})


@login_required
def activity(request):
    return jingo.render(request, 'devhub/addons/activity.html')


@dev_required
def edit(request, addon_id, addon):

    data = {
       'page': 'edit',
       'addon': addon,
       'tags': addon.tags.not_blacklisted().values_list('tag_text', flat=True),
       'previews': addon.previews.all(),
       }

    return jingo.render(request, 'devhub/addons/edit.html', data)


@dev_required
@owner_for_post_required
def ownership(request, addon_id, addon):
    forms = []
    # Authors.
    qs = AddonUser.objects.filter(addon=addon).order_by('position')
    user_form = AuthorFormSet(request.POST or None, queryset=qs)
    forms.append(user_form)
    # License. Clear out initial data if it's a builtin license.
    qs = addon.versions.order_by('-version')[:1]
    version = qs[0] if qs else None
    if version:
        instance, initial = version.license, None
        if getattr(instance, 'builtin', None):
            instance, initial = None, {'builtin': instance.builtin}
        license_form = LicenseForm(request.POST or None, initial=initial,
                                   instance=instance)
        forms.append(license_form)
    # Policy.
    policy_form = PolicyForm(request.POST or None, instance=addon,
                             initial=dict(has_priv=bool(addon.privacy_policy),
                                          has_eula=bool(addon.eula)))
    forms.append(policy_form)

    if request.method == 'POST' and all([form.is_valid() for form in forms]):
        # Authors.
        authors = user_form.save(commit=False)
        for author in authors:
            action = 'change' if author.id else 'add'
            author.addon = addon
            author.save()
            AddonLog.log(AddonUser, request, addon=addon,
                         action=action, author=author)
        # License.
        if version:
            license = license_form.save()
            addon.current_version.update(license=license)
            AddonLog.log(License, request, addon=addon, license=license)
        # Policy.
        policy_form.save(addon=addon)
        AddonLog.log(Addon, request, action='policy', form=policy_form)

        return redirect('devhub.addons.owner', addon_id)

    license_urls = dict(License.objects.builtins()
                        .values_list('builtin', 'url'))
    return jingo.render(request, 'devhub/addons/owner.html',
        dict(addon=addon, user_form=user_form, version=version,
             license_form=version and license_form, license_urls=license_urls,
             policy_form=policy_form, license_other_val=License.OTHER))


@dev_required
def payments(request, addon_id, addon):
    charity = None if addon.charity_id == amo.FOUNDATION_ORG else addon.charity
    charity_form = CharityForm(request.POST or None, instance=charity,
                               prefix='charity')
    contrib_form = ContribForm(request.POST or None, instance=addon,
                               initial=ContribForm.initial(addon))
    if request.method == 'POST':
        if contrib_form.is_valid():
            addon, valid = contrib_form.save(commit=False), True
            addon.wants_contributions = True
            recipient = contrib_form.cleaned_data['recipient']
            if recipient == 'dev':
                addon.charity = None
            elif recipient == 'moz':
                addon.charity_id = amo.FOUNDATION_ORG
            elif recipient == 'org':
                valid = charity_form.is_valid()
                if valid:
                    addon.charity = charity_form.save()
            if valid:
                addon.save()
                return redirect('devhub.addons.payments', addon_id)
    return jingo.render(request, 'devhub/addons/payments.html',
                        dict(addon=addon, charity_form=charity_form,
                            contrib_form=contrib_form))


@dev_required
@post_required
def disable_payments(request, addon_id, addon):
    addon.update(wants_contributions=False)
    return redirect('devhub.addons.payments', addon_id)


@dev_required
def profile(request, addon_id, addon):
    profile_form = ProfileForm(request.POST or None, instance=addon)

    if request.method == 'POST' and profile_form.is_valid():
        profile_form.save()
        AddonLog.log(Addon, request, action='profile', form=profile_form)
        return redirect('devhub.addons.profile', addon_id)

    return jingo.render(request, 'devhub/addons/profile.html',
                        dict(addon=addon, profile_form=profile_form))


def upload(request):
    if request.method == 'POST' and 'upload' in request.FILES:
        upload = request.FILES['upload']
        loc = path.path(settings.ADDONS_PATH) / 'temp' / uuid.uuid4().hex
        if not loc.dirname().exists():
            loc.dirname().makedirs()
        ext = path.path(upload.name).ext
        if ext in EXTENSIONS:
            loc += ext
        log.info('UPLOAD: %r (%s bytes) to %r' %
                 (upload.name, upload.size, loc))
        with open(loc, 'wb') as fd:
            for chunk in upload:
                fd.write(chunk)
        user = getattr(request, 'amo_user', None)
        fu = FileUpload.objects.create(path=loc, name=upload.name, user=user)
        tasks.validator.delay(fu.pk)
        return redirect('devhub.upload_detail', fu.pk)

    return jingo.render(request, 'devhub/upload.html')


def upload_detail(request, uuid):
    upload = get_object_or_404(FileUpload.uncached, uuid=uuid)
    return jingo.render(request, 'devhub/validation.html',
                        dict(upload=upload))


@dev_required
def addons_section(request, addon_id, addon, section, editable=False):

    models = {'basic': AddonFormBasic}

    if section not in models:
        return http.HttpResponseNotFound()

    if editable:
        if request.method == 'POST':
            form = models[section](request.POST, request.FILES,
                                  instance=addon)
            if form.is_valid():
                addon = form.save(addon)
                editable = False

                AddonLog.log(models[section], request, addon=addon,
                             action='edit '+section)
        else:
            form = models[section](instance=addon)
    else:
        form = False

    tags = addon.tags.not_blacklisted().values_list('tag_text', flat=True)

    data = {'addon': addon,
            'form': form,
            'lang': lang,
            'editable': editable,
            'tags': tags}

    return jingo.render(request,
                        'devhub/includes/addon_edit_%s.html' % section, data)
