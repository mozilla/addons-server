from django.db.models import Q
from django.views.decorators.cache import cache_page

import jingo
import jinja2
from tower import ugettext as _, ugettext_lazy as _lazy

import amo
from amo.helpers import urlparams
from amo.urlresolvers import reverse
from addons.models import Addon
from translations.models import Translation


@jinja2.contextfunction
def install_button(context, addon, version=None, show_eula=True,
                   show_contrib=True, show_warning=True, src='',
                   collection=None, size='', detailed=False):
    """If version isn't given, we use the latest version."""
    request = context['request']
    app, lang = context['APP'], context['LANG']
    show_eula = bool(request.GET.get('eula', show_eula))
    src = src or context.get('src') or request.GET.get('src', '')
    collection = ((collection.uuid if hasattr(collection, 'uuid') else None)
                   or collection
                   or context.get('collection')
                   or request.GET.get('collection')
                   or request.GET.get('collection_id')
                   or request.GET.get('collection_uuid'))
    button = install_button_factory(addon, app, lang, version,
                                    show_eula, show_contrib, show_warning,
                                    src, collection, size, detailed)
    installed = (request.user.is_authenticated() and
                 addon.id in request.amo_user.mobile_addons)
    c = {'button': button, 'addon': addon, 'version': button.version,
         'installed': installed}
    t = jingo.render_to_string(request, 'addons/button.html', c)
    return jinja2.Markup(t)


@jinja2.contextfunction
def big_install_button(context, addon, **kwargs):
    from addons.helpers import statusflags
    b = install_button(context, addon, detailed=True, size='prominent',
                       **kwargs)
    s = u'<div class="install-wrapper %s">%s</div>'
    return jinja2.Markup(s % (statusflags(context, addon), b))


def install_button_factory(*args, **kwargs):
    button = InstallButton(*args, **kwargs)
    # Order matters.  We want to highlight unreviewed before featured.  They
    # should be mutually exclusive, but you never know.
    classes = (('is_persona', PersonaInstallButton),
               ('unreviewed', UnreviewedInstallButton),
               ('self_hosted', SelfHostedInstallButton),
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

    def __init__(self, addon, app, lang, version=None, show_eula=True,
                 show_contrib=True, show_warning=True, src='', collection=None,
                 size='', detailed=False):
        self.addon, self.app, self.lang = addon, app, lang
        self.latest = version is None
        self.version = version or addon.current_version
        self.src = src
        self.collection = collection
        self.size = size
        self.detailed = detailed

        self.is_beta = self.version and self.version.is_beta
        version_unreviewed = (self.version and self.version.is_unreviewed)
        self.unreviewed = (addon.is_unreviewed() or version_unreviewed or
                           self.is_beta)
        self.self_hosted = addon.status == amo.STATUS_LISTED
        self.featured = (not self.unreviewed
                         and not self.self_hosted
                         and not self.is_beta
                         and addon.is_featured(app, lang)
                         or addon.is_category_featured(app, lang))
        self.is_persona = addon.type == amo.ADDON_PERSONA

        self.accept_eula = addon.has_eula and not show_eula
        self.show_contrib = (show_contrib and addon.takes_contributions
                             and addon.annoying == amo.CONTRIB_ROADBLOCK)
        self.show_eula = not self.show_contrib and show_eula and addon.has_eula
        self.show_warning = show_warning and (self.unreviewed or
                                              self.self_hosted)

    def prepare(self):
        """Called after the class is set to manage eulas, contributions."""
        # Get a copy for this instance.
        self.button_class = list(self.__class__.button_class)
        self.install_class = list(self.__class__.install_class)
        tests = (self.show_eula, 'eula'), (self.show_contrib, 'contrib')
        for pred, cls in tests:
            if bool(pred):
                try:
                    self.button_class.remove('download')
                except ValueError:
                    pass
                self.button_class.append(cls)
                self.button_class.append('go')
                self.install_class.append(cls)

        if self.accept_eula:
            self.install_class.append('accept')
        if self.size:
            self.button_class.append(self.size)
        if self.is_beta:
            self.install_class.append('beta')

    def attrs(self):
        rv = {}
        addon = self.addon
        if addon.takes_contributions and addon.annoying == amo.CONTRIB_AFTER:
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
        platform = file.platform_id
        if self.latest and (
            self.addon.status == file.status == amo.STATUS_PUBLIC):
            url = file.latest_xpi_url()
        else:
            url = file.get_url_path(self.app, self.src)

        if platform == amo.PLATFORM_ALL.id:
            text, os = _('Download Now'), None
        else:
            text, os = _('Download'), amo.PLATFORMS[platform]

        if self.show_eula:
			# L10n: please keep &nbsp; in the string so the &rarr; does not wrap
            text, url = _('Continue to Download&nbsp;&rarr;'), file.eula_url()
        elif self.accept_eula:
            text = _('Accept and Download')
        elif self.show_contrib:
            # The eula doesn't exist or has been hit already.
			# L10n: please keep &nbsp; in the string so the &rarr; does not wrap
            text = _('Continue to Download&nbsp;&rarr;')
            roadblock = reverse('addons.roadblock', args=[self.addon.id])
            url = urlparams(roadblock, eula='', version=self.version.version)

        return text, url, os

    def fix_link(self, url):
        if self.src:
            url = urlparams(url, src=self.src)
        if self.collection:
            url = urlparams(url, collection=self.collection)
        return url


class FeaturedInstallButton(InstallButton):
    install_class = ['featuredaddon']
    install_text = _lazy(u'Featured', 'install_button')


class UnreviewedInstallButton(InstallButton):
    install_class = ['unreviewed']
    install_text = _lazy(u'Not Reviewed', 'install_button')
    button_class = 'download caution'.split()


class SelfHostedInstallButton(InstallButton):
    install_class = ['selfhosted']
    install_text = _lazy(u'Self Hosted', 'install_button')
    button_class = ['go']

    def links(self):
		# L10n: please keep &nbsp; in the string so the &rarr; does not wrap
        return [Link(_('Continue to Website&nbsp;&rarr;'), self.addon.homepage)]


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
def js(request):
    return jingo.render(request, 'addons/popups.html',
                        content_type='text/javascript')


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

    # Self-Hosted.
    addons.append(Addon.objects.filter(status=amo.STATUS_LISTED,
                                       inactive=False)[0])
    addons[-1].tag = 'self-hosted'

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

    return jingo.render(request, 'addons/smorgasbord.html',
                        {'addons': addons, 'beta': beta})
