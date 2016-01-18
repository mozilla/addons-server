from django.db.models import Q
from django.db.transaction import non_atomic_requests
from django.shortcuts import render
from django.views.decorators.cache import cache_page

import jingo
import jinja2
from tower import ugettext as _, ugettext_lazy as _lazy

from olympia import amo
from olympia.amo.helpers import urlparams
from olympia.amo.urlresolvers import reverse
from olympia.addons.models import Addon
from olympia.translations.models import Translation


@jinja2.contextfunction
def install_button(context, addon, version=None, show_contrib=True,
                   show_warning=True, src='', collection=None, size='',
                   detailed=False, mobile=False, impala=False,
                   latest_beta=False):
    """
    If version isn't given, we use the latest version. You can set latest_beta
    parameter to use latest beta version instead.
    """
    assert not (version and latest_beta), (
        'Only one of version and latest_beta can be specified')

    request = context['request']
    app, lang = context['APP'], context['LANG']
    src = src or context.get('src') or request.GET.get('src', '')
    collection = ((collection.uuid if hasattr(collection, 'uuid') else None)
                  or collection
                  or context.get('collection')
                  or request.GET.get('collection')
                  or request.GET.get('collection_id')
                  or request.GET.get('collection_uuid'))
    button = install_button_factory(addon, app, lang, version, show_contrib,
                                    show_warning, src, collection, size,
                                    detailed, impala,
                                    latest_beta)
    installed = (request.user.is_authenticated() and
                 addon.id in request.user.mobile_addons)
    c = {'button': button, 'addon': addon, 'version': button.version,
         'installed': installed}
    if impala:
        template = 'addons/impala/button.html'
    elif mobile:
        template = 'addons/mobile/button.html'
    else:
        template = 'addons/button.html'
    t = jingo.render_to_string(request, template, c)
    return jinja2.Markup(t)


@jinja2.contextfunction
def big_install_button(context, addon, **kwargs):
    from olympia.addons.helpers import statusflags
    flags = jinja2.escape(statusflags(context, addon))
    button = install_button(context, addon, detailed=True, size='prominent',
                            **kwargs)
    markup = u'<div class="install-wrapper %s">%s</div>' % (flags, button)
    return jinja2.Markup(markup)


@jinja2.contextfunction
def mobile_install_button(context, addon, **kwargs):
    from olympia.addons.helpers import statusflags
    button = install_button(context, addon, detailed=True, size='prominent',
                            mobile=True, **kwargs)
    flags = jinja2.escape(statusflags(context, addon))
    markup = u'<div class="install-wrapper %s">%s</div>' % (flags, button)
    return jinja2.Markup(markup)


def install_button_factory(*args, **kwargs):
    button = InstallButton(*args, **kwargs)
    # Order matters.  We want to highlight unreviewed before featured.  They
    # should be mutually exclusive, but you never know.
    classes = (('is_persona', PersonaInstallButton),
               ('lite', LiteInstallButton),
               ('unreviewed', UnreviewedInstallButton),
               ('featured', FeaturedInstallButton))
    for pred, cls in classes:
        if getattr(button, pred, False):
            button.__class__ = cls
            break
    button.prepare()
    return button


class InstallButton(object):
    button_class = ['download']
    install_class = []
    install_text = ''

    def __init__(self, addon, app, lang, version=None, show_contrib=True,
                 show_warning=True, src='', collection=None, size='',
                 detailed=False, impala=False,
                 latest_beta=False):
        self.addon, self.app, self.lang = addon, app, lang
        self.latest = version is None
        self.version = version
        if not self.version:
            self.version = (addon.current_beta_version if latest_beta
                            else addon.current_version)
        self.src = src
        self.collection = collection
        self.size = size
        self.detailed = detailed
        self.impala = impala

        self.is_beta = self.version and self.version.is_beta
        version_unreviewed = self.version and self.version.is_unreviewed
        self.lite = self.version and self.version.is_lite
        self.unreviewed = (addon.is_unreviewed() or version_unreviewed or
                           self.is_beta)
        self.featured = (not self.unreviewed
                         and not self.lite
                         and not self.is_beta
                         and addon.is_featured(app, lang))
        self.is_persona = addon.type == amo.ADDON_PERSONA

        self._show_contrib = show_contrib
        self.show_contrib = (show_contrib and addon.takes_contributions
                             and addon.annoying == amo.CONTRIB_ROADBLOCK)
        self.show_warning = show_warning and self.unreviewed

    def prepare(self):
        """Called after the class is set to manage contributions."""
        # Get a copy for this instance.
        self.button_class = list(self.__class__.button_class)
        self.install_class = list(self.__class__.install_class)
        if self.show_contrib:
            try:
                self.button_class.remove('download')
            except ValueError:
                pass
            self.button_class += ['contrib', 'go']
            self.install_class.append('contrib')

        if self.size:
            self.button_class.append(self.size)
        if self.is_beta:
            self.install_class.append('beta')

    def attrs(self):
        rv = {}
        addon = self.addon
        if (self._show_contrib and addon.takes_contributions
                and addon.annoying == amo.CONTRIB_AFTER):
            rv['data-after'] = 'contrib'
        if addon.type == amo.ADDON_SEARCH:
            rv['data-search'] = 'true'
        return rv

    def links(self):
        if not self.version:
            return []
        rv = []
        files = [f for f in self.version.all_files
                 if f.status in amo.VALID_STATUSES]
        for file in files:
            text, url, os = self.file_details(file)
            rv.append(Link(text, self.fix_link(url), os, file))
        return rv

    def file_details(self, file):
        platform = file.platform
        if self.latest and not self.is_beta and (
                self.addon.status == file.status == amo.STATUS_PUBLIC):
            url = file.latest_xpi_url()
        elif self.latest and self.is_beta and self.addon.show_beta:
            url = file.latest_xpi_url(beta=True)
        else:
            url = file.get_url_path(self.src)

        if platform == amo.PLATFORM_ALL.id:
            text, os = _('Download Now'), None
        else:
            text, os = _('Download'), amo.PLATFORMS[platform]

        if self.show_contrib:
            # L10n: please keep &nbsp; in the string so &rarr; does not wrap.
            text = jinja2.Markup(_('Continue to Download&nbsp;&rarr;'))
            roadblock = reverse('addons.roadblock', args=[self.addon.id])
            url = urlparams(roadblock, version=self.version.version)

        return text, url, os

    def fix_link(self, url):
        if self.src:
            url = urlparams(url, src=self.src)
        if self.collection:
            url = urlparams(url, collection_id=self.collection)
        return url


class FeaturedInstallButton(InstallButton):
    install_class = ['featuredaddon']
    install_text = _lazy(u'Featured', 'install_button')


class UnreviewedInstallButton(InstallButton):
    install_class = ['unreviewed']
    install_text = _lazy(u'Not Reviewed', 'install_button')
    button_class = 'download caution'.split()


class LiteInstallButton(InstallButton):
    install_class = ['lite']
    button_class = ['caution']
    install_text = _lazy(u'Experimental', 'install_button')


class PersonaInstallButton(InstallButton):
    install_class = ['persona']

    def links(self):
        return [Link(_(u'Add to {0}').format(unicode(self.app.pretty)),
                     reverse('addons.detail', args=[amo.PERSONAS_ADDON_ID]))]

    def attrs(self):
        rv = super(PersonaInstallButton, self).attrs()
        rv['data-browsertheme'] = self.addon.persona.json_data
        return rv


class Link(object):

    def __init__(self, text, url, os=None, file=None):
        self.text, self.url, self.os, self.file = text, url, os, file


# Cache it for a year.
@cache_page(60 * 60 * 24 * 365)
@non_atomic_requests
def js(request):
    return render(request, 'addons/popups.html',
                  content_type='text/javascript')


@non_atomic_requests
def smorgasbord(request):
    """
    Gather many different kinds of tasty add-ons together.

    Great for testing install buttons.
    """
    def _compat(min, max):
        # Helper for faking compatible_apps.
        return {'min': {'version': min}, 'max': {'version': max}}

    addons = []
    normal_version = _compat('1.0', '10.0')
    older_version = _compat('1.0', '2.0')
    newer_version = _compat('9.0', '10.0')

    def all_versions(addon, base_tag):
        x = (('', normal_version),
             (' + older version', older_version),
             (' + newer version', newer_version))
        for extra, version in x:
            a = addon()
            a.tag = base_tag + extra
            a.compatible_apps[request.APP] = version
            addons.append(a)

    # Featured.
    featured = Addon.objects.featured(request.APP)
    addons.append(featured[0])
    addons[-1].tag = 'featured'

    normal = Addon.objects.listed(request.APP).exclude(id__in=featured)

    # Normal, Older Version, Newer Version.
    all_versions(lambda: normal[0], 'normal')

    # Unreviewed.
    exp = Addon.objects.unreviewed()
    all_versions(lambda: exp[0], 'unreviewed')

    # Multiple Platforms.
    addons.append(Addon.objects.get(id=2313))
    addons[-1].tag = 'platformer'

    # Multiple Platforms + EULA.
    addons.append(Addon.objects.get(id=2313))
    addons[-1].eula = Translation(localized_string='xxx')
    addons[-1].tag = 'platformer + eula'

    # Incompatible Platform + EULa.
    addons.append(Addon.objects.get(id=5308))
    addons[-1].eula = Translation(localized_string='xxx')
    addons[-1].tag = 'windows/linux-only + eula'

    # Incompatible Platform.
    all_versions(lambda: Addon.objects.get(id=5308), 'windows/linux-only')

    # EULA.
    eula = (Q(eula__isnull=False, eula__localized_string__isnull=False)
            & ~Q(eula__localized_string=''))
    addons.append(normal.filter(eula)[0])
    addons[-1].tag = 'eula'
    addons.append(exp.filter(eula)[0])
    addons[-1].tag = 'eula + unreviewed'

    # Contributions.
    addons.append(normal.filter(annoying=1)[0])
    addons[-1].tag = 'contrib: passive'
    addons.append(normal.filter(annoying=2)[0])
    addons[-1].tag = 'contrib: after'
    addons.append(normal.filter(annoying=3)[0])
    addons[-1].tag = 'contrib: roadblock'
    addons.append(Addon.objects.get(id=2608))
    addons[-1].tag = 'after + eula'
    addons.append(Addon.objects.get(id=8442))
    addons[-1].tag = 'roadblock + eula'

    # Other App.
    addons.append(Addon.objects.get(id=5326))
    addons[-1].tag = 'tbird'

    # Mobile.
    addons.append(Addon.objects.get(id=53476))
    addons[-1].tag = 'mobile'

    # Search Engine.
    addons.append(Addon.objects.filter(type=amo.ADDON_SEARCH)[0])
    addons[-1].tag = 'search engine'

    # Beta Version
    beta = normal.filter(versions__files__status=amo.STATUS_BETA)[0]
    beta.tag = 'beta version'

    # Theme.

    # Persona.
    addons.append(Addon.objects.filter(type=amo.ADDON_PERSONA)[0])
    addons[-1].tag = 'persona'

    # Future Version.
    # No versions.

    return render(request, 'addons/smorgasbord.html',
                  {'addons': addons, 'beta': beta})
