import jingo
import jinja2
from l10n import ugettext as _, ugettext_lazy as _lazy

import amo
from amo.helpers import urlparams
from addons.models import Addon


@jinja2.contextfunction
def install_button(context, addon, version=None, show_eula=True,
                   show_contrib=True):
    """If version isn't given, we use the latest version."""
    app, lang = context['APP'], context['LANG']
    show_eula = bool(context['request'].GET.get('eula', show_eula))
    button = install_button_factory(addon, app, lang, version,
                                    show_eula, show_contrib)
    c = {'button': button, 'addon': addon, 'version': button.version,
         'APP': app}
    t = jingo.env.get_template('addons/install-button.html').render(c)
    return jinja2.Markup(t)


def install_button_factory(addon, app, lang, version=None, show_eula=True,
                           show_contrib=True):
    button = InstallButton(addon, app, lang, version, show_eula, show_contrib)
    # Order matters.  We want to highlight unreviewed before featured.  They
    # should be mutually exclusive, but you never know.
    classes = (('unreviewed', UnreviewedInstallButton),
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
                 show_contrib=True):
        self.addon, self.app, self.lang = addon, app, lang
        self.latest = version is None
        self.version = version or addon.current_version

        self.featured = addon.is_featured(app, lang)
        self.unreviewed = addon.is_unreviewed() or self.version.is_unreviewed
        self.self_hosted = addon.status == amo.STATUS_LISTED

        self.show_eula = show_eula and addon.has_eula
        self.show_contrib = (show_contrib and addon.takes_contributions
                             and addon.annoying == amo.CONTRIB_ROADBLOCK)

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
                self.install_class.append(cls)

    def attrs(self):
        rv = {}
        addon = self.addon
        if addon.takes_contributions and addon.annoying == amo.CONTRIB_AFTER:
            rv['data-after'] = 'contrib'
        if addon.type_id == amo.ADDON_SEARCH:
            rv['data-search'] = 'true'
        return rv

    def links(self):
        rv = []
        for file in self.version.files.all():
            platform = file.platform_id
            # TODO(jbalogh): this is wrong if we got a version argument.
            url = file.latest_xpi_url()
            if platform == amo.PLATFORM_ALL.id:
                text, os = _('Download Now'), None
            else:
                text, os = _('Download'), amo.PLATFORMS[platform]
            if self.show_eula:
                text, url = _('Continue to Download &rarr;'), file.eula_url()
            elif self.show_contrib:
                # The eula doesn't exist or has been hit already.
                text = _('Continue to Download &rarr;')
                roadblock = self.addon.meet_the_dev_url(extra='roadblock')
                url = urlparams(roadblock, eula='')
            rv.append(Link(text, url, os, file))
        return rv


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
        return [Link(_('Continue to Website &rarr;'), self.addon.homepage)]


class Link(object):

    def __init__(self, text, url, os=None, file=None):
        self.text, self.url, self.os, self.file = text, url, os, file


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

    # Featured.
    featured = Addon.objects.featured(request.APP)
    addons.append(featured[0])
    addons[-1].tag = 'featured'

    # Normal.
    normal = Addon.objects.listed(request.APP).exclude(id__in=featured)
    addon = normal[0]
    addon.tag = 'normal'
    addon.compatible_apps[request.APP] = _compat('1.0', '10.0')
    addons.append(addon)

    # Older version.
    addon = normal[0]
    addon.tag = 'older version'
    addon.compatible_apps[request.APP] = _compat('1.0', '2.0')
    addons.append(addon)

    # Newer version.
    addon = normal[0]
    addon.tag = 'newer version'
    addon.compatible_apps[request.APP] = _compat('9.0', '10.0')
    addons.append(addon)

    # Unreviewed.
    exp = Addon.objects.experimental()
    addons.append(exp[0])
    addons[-1].tag = 'unreviewed'

    # Multiple Platforms.
    addons.append(Addon.objects.get(id=2313))
    addons[-1].tag = 'platformer'

    # Incompatible Platform.
    addons.append(Addon.objects.get(id=5308))
    addons[-1].tag = 'windows-only'

    # Self-Hosted.
    addons.append(Addon.objects.filter(status=amo.STATUS_LISTED,
                                       inactive=False)[0])
    addons[-1].tag = 'self-hosted'

    # EULA.
    addons.append(normal.filter(eula__isnull=False)[0])
    addons[-1].tag = 'eula'
    addons.append(exp.filter(eula__isnull=False)
                  .exclude(eula__localized_string='')[0])
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
    # Theme.
    # Persona.
    # Future Version.
    # No versions.

    return jingo.render(request, 'addons/smorgasbord.html',
                        {'addons': addons})
