import functools
import uuid

from django import http
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect

import commonware.log
import jingo
import path
from tower import ugettext_lazy as _lazy

import amo.utils
from amo.decorators import login_required
from access import acl
from addons.models import Addon, AddonUser, AddonLog
from addons.views import BaseFilter
from files.models import FileUpload
from versions.models import License
from . import tasks
from .forms import AuthorFormSet, LicenseForm, PolicyForm

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
def addons_dashboard(request):
    TYPE = amo.ADDON_ANY
    addons, filter = addon_listing(request, TYPE)
    addons = amo.utils.paginate(request, addons, per_page=10)
    return jingo.render(request, 'devhub/addons/dashboard.html',
                        {'addons': addons, 'sorting': filter.field,
                         'sort_opts': filter.opts})


# TODO: If user is not a developer, redirect to url('devhub.addons').
@login_required
def addons_activity(request):
    return jingo.render(request, 'devhub/addons/activity.html')


@dev_required
def addons_edit(request, addon_id, addon):
    tags_dev, tags_user = addon.tags_partitioned_by_developer

    data = {
        'page': 'edit',
        'addon': addon,
        'tags_user': [tag.tag_text for tag in tags_dev],
        'tags_dev': [tag.tag_text for tag in tags_user],
        'previews': addon.previews.all(),
        }

    return jingo.render(request, 'devhub/addons/edit.html', data)


@dev_required
@owner_for_post_required
def addons_owner(request, addon_id, addon):
    forms = []
    # Authors.
    qs = AddonUser.objects.filter(addon=addon)
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
def addons_payments(request, addon_id, addon):
    return jingo.render(request, 'devhub/addons/payments.html',
                        dict(addon=addon))


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
