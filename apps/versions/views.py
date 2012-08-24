import posixpath

from django import http
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.cache import never_cache

import caching.base as caching
import commonware.log
import jingo
from mobility.decorators import mobile_template
import waffle

import amo
from amo.urlresolvers import reverse
from amo.utils import urlparams, HttpResponseSendFile
from access import acl
from addons.decorators import addon_view_factory
from addons.models import Addon
from files.models import File
from versions.models import Version


# The version detail page redirects to the version within pagination, so we
# need to enforce the number of versions per page.
PER_PAGE = 30
addon_view = addon_view_factory(Addon.objects.valid)

log = commonware.log.getLogger('z.versions')


@addon_view
@mobile_template('versions/{mobile/}version_list.html')
def version_list(request, addon, template):
    qs = (addon.versions.filter(files__status__in=amo.VALID_STATUSES)
          .distinct().order_by('-created'))
    versions = amo.utils.paginate(request, qs, PER_PAGE)
    versions.object_list = list(versions.object_list)
    Version.transformer(versions.object_list)
    return jingo.render(request, template,
                        {'addon': addon, 'versions': versions})


@addon_view
def version_detail(request, addon, version_num):
    qs = (addon.versions.filter(files__status__in=amo.VALID_STATUSES)
          .distinct().order_by('-created'))
    # Use cached_with since values_list won't be cached.
    f = lambda: _find_version_page(qs, addon, version_num)
    return caching.cached_with(qs, f, 'vd:%s:%s' % (addon.id, version_num))


def _find_version_page(qs, addon, version_num):
    ids = list(qs.values_list('version', flat=True))
    url = reverse('addons.versions', args=[addon.slug])
    if version_num in ids:
        page = 1 + ids.index(version_num) / PER_PAGE
        return redirect(urlparams(url, 'version-%s' % version_num, page=page))
    else:
        raise http.Http404()


@addon_view
def update_info(request, addon, version_num):
    qs = addon.versions.filter(version=version_num,
                               files__status__in=amo.VALID_STATUSES)
    if not qs:
        raise http.Http404()
    serve_xhtml = ('application/xhtml+xml' in
                   request.META.get('HTTP_ACCEPT', '').lower())
    return jingo.render(request, 'versions/update_info.html',
                        {'version': qs[0], 'serve_xhtml': serve_xhtml},
                        content_type='application/xhtml+xml')


def update_info_redirect(request, version_id):
    version = get_object_or_404(Version, pk=version_id)
    return redirect(reverse('addons.versions.update_info',
                            args=(version.addon.id, version.version)),
                    permanent=True)


@never_cache
def download_watermarked(request, file_id):
    if not waffle.switch_is_active('marketplace'):
        raise http.Http404()

    file = get_object_or_404(File.objects, pk=file_id)
    addon = get_object_or_404(Addon.objects, pk=file.version.addon_id)
    author = request.check_ownership(addon, require_owner=False)
    user = request.amo_user

    if not author:
        if (not addon.is_premium() or addon.is_disabled
            or file.status == amo.STATUS_DISABLED):
            raise http.Http404()

        if request.user.is_anonymous():
            log.debug('Anonymous user, checking hash: %s' % file_id)
            email = request.GET.get(amo.WATERMARK_KEY, None)
            hsh = request.GET.get(amo.WATERMARK_KEY_HASH, None)

            user = addon.get_user_from_hash(email, hsh)
            if not user:
                log.debug('Watermarking denied, no user: %s, %s, %s'
                          % (file_id, email, hsh))
                return http.HttpResponseForbidden()

        if not addon.has_purchased(user):
            log.debug('Watermarking denied, not purchased: %s, %s'
                      % (file_id, user.id))
            return http.HttpResponseForbidden()

    dest = file.watermark(user)
    if not dest:
        # TODO(andym): the watermarking is already in progress and we've
        # got multiple requests from the same users for the same file
        # perhaps this should go into a loop.
        log.debug('Watermarking in progress: %s, %s' % (file_id, user.id))
        raise http.Http404()

    log.debug('Serving watermarked file: %s, %s' % (file_id, user.id))
    return HttpResponseSendFile(request, dest,
                                content_type='application/xp-install')


# Should accept junk at the end for filename goodness.
def download_file(request, file_id, type=None):
    file = get_object_or_404(File.objects, pk=file_id)
    addon = get_object_or_404(Addon.objects, pk=file.version.addon_id)

    if addon.is_premium():
        return http.HttpResponseForbidden()

    if addon.is_disabled or file.status == amo.STATUS_DISABLED:
        if (acl.check_addon_ownership(request, addon, viewer=True,
                                      ignore_disabled=True) or
            acl.check_reviewer(request)):
            return HttpResponseSendFile(request, file.guarded_file_path,
                                        content_type='application/xp-install')
        else:
            raise http.Http404()

    attachment = (type == 'attachment' or not request.APP.browser)

    loc = file.get_mirror(addon, attachment=attachment)
    response = http.HttpResponseRedirect(loc)
    response['X-Target-Digest'] = file.hash
    return response


guard = lambda: Addon.objects.filter(_current_version__isnull=False)


@addon_view_factory(guard)
def download_latest(request, addon, type='xpi', platform=None):
    platforms = [amo.PLATFORM_ALL.id]
    if platform is not None and int(platform) in amo.PLATFORMS:
        platforms.append(int(platform))
    files = File.objects.filter(platform__in=platforms,
                                version=addon._current_version_id)
    try:
        # If there's a file matching our platform, it'll float to the end.
        file = sorted(files, key=lambda f: f.platform_id == platforms[-1])[-1]
    except IndexError:
        raise http.Http404()
    args = [file.id, type] if type else [file.id]
    pattern = ('downloads.watermarked' if addon.is_premium()
               else 'downloads.file')
    url = posixpath.join(reverse(pattern, args=args), file.filename)
    if request.GET:
        url += '?' + request.GET.urlencode()
    return redirect(url)
