import collections
import os
import shutil
import time
import zipfile
from xml.dom.minidom import parse

from django import forms
from django.conf import settings

from tower import ugettext as _

import amo
from applications.models import AppVersion


def get_text_value(xml, tag):
    node = xml.getElementsByTagName('em:%s' % tag)[0]
    if node.childNodes:
        textnode = node.childNodes[0]
        return textnode.wholeText


def parse_xpi(xpi, addon=None):
    from addons.models import Addon
    # Extract to /tmp
    path = os.path.join(settings.TMP_PATH, str(time.time()))
    os.makedirs(path)

    # Validating that we have no member files that try to break out of
    # the destination path.  NOTE: This will be obsolete when this bug is
    # fixed: http://bugs.python.org/issue6972
    zip = zipfile.ZipFile(xpi)

    for f in zip.namelist():
        if '..' in f or f.startswith('/'):
            raise forms.ValidationError(_('Invalid archive.'))

    zip.extractall(path)

    # read RDF and store in clean_data
    rdf = parse(os.path.join(path, 'install.rdf'))
    # XPIs use their own type ids
    XPI_TYPES = {'2': amo.ADDON_EXTENSION, '4': amo.ADDON_THEME,
                 '8': amo.ADDON_LPADDON}

    apps = []
    App = collections.namedtuple('App', 'appdata id min max')
    for node in rdf.getElementsByTagName('em:targetApplication'):
        app = amo.APP_GUIDS.get(get_text_value(node, 'id'))
        min_val = get_text_value(node, 'minVersion')
        max_val = get_text_value(node, 'maxVersion')

        try:
            min = AppVersion.objects.get(application=app.id,
                                         version=min_val)
            max = AppVersion.objects.get(application=app.id,
                                         version=max_val)
        except AppVersion.DoesNotExist:
            continue

        if app:
            apps.append(App(appdata=app, id=app.id, min=min, max=max))

    guid = get_text_value(rdf, 'id')
    addon_type = XPI_TYPES.get(get_text_value(rdf, 'type'))

    if addon and addon.guid != guid:
        raise forms.ValidationError(_("GUID doesn't match add-on"))
    if not addon and Addon.objects.filter(guid=guid):
        raise forms.ValidationError(_('Duplicate GUID found.'))

    if addon and addon.type != addon_type:
        raise forms.ValidationError(
            _("<em:type> doesn't match add-on"))

    shutil.rmtree(path)
    return dict(
        guid=guid,
        name=get_text_value(rdf, 'name'),
        description=get_text_value(rdf, 'description'),
        version=get_text_value(rdf, 'version'),
        homepage=get_text_value(rdf, 'homepageURL'),
        type=addon_type,
        apps=apps,
    )
