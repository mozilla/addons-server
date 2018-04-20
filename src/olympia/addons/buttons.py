from django.template.loader import render_to_string
from django.utils.translation import (
    pgettext_lazy, ugettext, ugettext_lazy as _)

import jinja2

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import urlparams
from olympia.amo.urlresolvers import reverse


@jinja2.contextfunction
def install_button(context, addon, version=None,
                   show_warning=True, src='', collection=None, size='',
                   detailed=False, impala=False, show_download_anyway=False):
    """
    If version isn't given, we use the latest version.
    """
    request = context['request']
    app, lang = context['APP'], context['LANG']
    src = src or context.get('src') or request.GET.get('src', '')
    collection = ((collection.uuid if hasattr(collection, 'uuid') else None) or
                  collection or
                  context.get('collection') or
                  request.GET.get('collection') or
                  request.GET.get('collection_id') or
                  request.GET.get('collection_uuid'))
    button = install_button_factory(
        addon, app, lang, version=version,
        show_warning=show_warning, src=src, collection=collection, size=size,
        detailed=detailed, impala=impala,
        show_download_anyway=show_download_anyway)
    installed = (request.user.is_authenticated() and
                 addon.id in request.user.mobile_addons)
    context = {
        'button': button, 'addon': addon, 'version': button.version,
        'installed': installed
    }
    if impala:
        template = 'addons/impala/button.html'
    else:
        template = 'addons/button.html'
    return jinja2.Markup(render_to_string(template, context, request=request))


@jinja2.contextfunction
def big_install_button(context, addon, **kwargs):
    from olympia.addons.templatetags.jinja_helpers import statusflags
    flags = jinja2.escape(statusflags(context, addon))
    button = install_button(
        context, addon, detailed=True, show_download_anyway=True,
        size='prominent', **kwargs)
    markup = u'<div class="install-wrapper %s">%s</div>' % (flags, button)
    return jinja2.Markup(markup)


def install_button_factory(*args, **kwargs):
    button = InstallButton(*args, **kwargs)
    # Order matters.  We want to highlight unreviewed before featured.  They
    # should be mutually exclusive, but you never know.
    classes = (('is_persona', PersonaInstallButton),
               ('unreviewed', UnreviewedInstallButton),
               ('experimental', ExperimentalInstallButton),
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

    def __init__(self, addon, app, lang, version=None,
                 show_warning=True, src='', collection=None, size='',
                 detailed=False, impala=False, show_download_anyway=False):
        self.addon, self.app, self.lang = addon, app, lang
        self.latest = version is None
        self.version = version
        if not self.version:
            self.version = addon.current_version
        self.src = src
        self.collection = collection
        self.size = size
        self.detailed = detailed
        self.show_download_anyway = show_download_anyway
        self.impala = impala

        version_unreviewed = self.version and self.version.is_unreviewed
        self.experimental = addon.is_experimental
        self.unreviewed = addon.is_unreviewed() or version_unreviewed
        self.featured = (not self.unreviewed and
                         not self.experimental and
                         addon.is_featured(app, lang))
        self.is_persona = addon.type == amo.ADDON_PERSONA

        self.show_warning = show_warning and self.unreviewed

    def prepare(self):
        """Called after the class is set to manage additional properties."""
        # Get a copy for this instance.
        self.button_class = list(self.__class__.button_class)
        self.install_class = list(self.__class__.install_class)

        if self.size:
            self.button_class.append(self.size)

    def attrs(self):
        rv = {}
        addon = self.addon
        if addon.type == amo.ADDON_SEARCH:
            rv['data-search'] = 'true'
        if addon.type in amo.NO_COMPAT:
            rv['data-no-compat-necessary'] = 'true'
        return rv

    def links(self):
        if not self.version:
            return []
        rv = []
        files = [f for f in self.version.all_files
                 if f.status in amo.VALID_FILE_STATUSES]
        for file in files:
            text, url, download_url, os = self.file_details(file)
            rv.append(Link(text, self.fix_link(url),
                           self.fix_link(download_url), os, file))
        return rv

    def file_details(self, file):
        platform = file.platform
        if self.latest and (
                self.addon.status == file.status == amo.STATUS_PUBLIC):
            url = file.latest_xpi_url()
            download_url = file.latest_xpi_url(attachment=True)
        else:
            url = file.get_url_path(self.src)
            download_url = file.get_url_path(self.src, attachment=True)

        if platform == amo.PLATFORM_ALL.id:
            text, os = ugettext('Download Now'), None
        else:
            text, os = ugettext('Download'), amo.PLATFORMS[platform]

        return text, url, download_url, os

    def fix_link(self, url):
        if self.src:
            url = urlparams(url, src=self.src)
        if self.collection:
            url = urlparams(url, collection_id=self.collection)
        return url


class FeaturedInstallButton(InstallButton):
    install_class = ['featuredaddon']
    install_text = _(u'Featured')


class UnreviewedInstallButton(InstallButton):
    install_class = ['unreviewed']
    install_text = pgettext_lazy('install_button', u'Not Reviewed')
    button_class = 'download caution'.split()


class ExperimentalInstallButton(InstallButton):
    install_class = ['lite']
    button_class = ['caution']
    install_text = pgettext_lazy('install_button', u'Experimental')


class PersonaInstallButton(InstallButton):
    install_class = ['persona']

    def links(self):
        return [Link(ugettext(u'Add to {0}').format(unicode(self.app.pretty)),
                     reverse('addons.detail', args=[amo.PERSONAS_ADDON_ID]))]

    def attrs(self):
        rv = super(PersonaInstallButton, self).attrs()
        rv['data-browsertheme'] = self.addon.persona.json_data
        return rv


class Link(object):

    def __init__(self, text, url, download_url=None, os=None, file=None):
        self.text, self.url, self.download_url, self.os, self.file = (
            text, url, download_url, os, file)
