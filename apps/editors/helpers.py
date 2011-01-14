import os

from django.conf import settings
import django_tables as tables
import jinja2
from jingo import register
from tower import ugettext_lazy as _, ungettext as ngettext

import amo
from editors.models import ViewEditorQueue
from amo.helpers import page_title
from amo.urlresolvers import reverse


@register.function
@jinja2.contextfunction
def editor_page_title(context, title=None, addon=None):
    """Wrapper for editor page titles.  Eerily similar to dev_page_title."""
    if addon:
        title = u'%s :: %s' % (title, addon.name)
    else:
        devhub = _('Editor Tools')
        title = '%s :: %s' % (title, devhub) if title else devhub
    return page_title(context, title)


class ViewEditorQueueTable(tables.ModelTable):
    addon_name = tables.Column(verbose_name=_(u'Addon'))
    addon_type_id = tables.Column(verbose_name=_(u'Type'))
    days_since_created = tables.Column(verbose_name=_(u'Waiting Time'))
    flags = tables.Column()
    applications = tables.Column()
    additional_info = tables.Column(verbose_name=_(u'Additional Information'))

    class Meta:
        model = ViewEditorQueue
        sortable = True
        exclude = ['id', 'version_id', 'admin_review',
                   'hours_since_created',
                   'days_since_nominated', 'hours_since_nominated',
                   'platform_id', 'is_site_specific',
                   'version_max', 'version_min', 'version_apps']

    def render_addon_name(self, row):
        return u'<a href="%s">%s</a>' % (reverse('editors.review',
                                                 args=[row.version_id]),
                                         jinja2.escape(row.addon_name))

    def render_addon_type_id(self, row):
        return amo.ADDON_TYPE[row.addon_type_id]

    def render_additional_info(self, row):
        if row.is_site_specific:
            r = _(u'Site Specific')
        elif row.platform_id != amo.PLATFORM_ALL.id:
            # L10n: first argument is the platform such as Linux, Mac OS X
            r = _(u'{0} only').format(amo.PLATFORMS[row.platform_id].name)
        else:
            r = ''
        return jinja2.escape(r)

    def render_applications(self, row):
        app_ids = self._explode_concat(row.applications)
        # _apps = self._explode_concat(row.version_apps)
        # version_min = dict(zip(_apps, self._explode_concat(row.version_min)))
        # version_max = dict(zip(_apps, self._explode_concat(row.version_max)))

        icon = u'<div class="app-icon ed-sprite-%s"></div>'
        return u' '.join(icon % amo.APPS_ALL[i].short for i in app_ids)

    def render_days_since_created(self, row):
        if row.days_since_created == 1:
            # L10n: first argument is number of hours
            r = ngettext(u'{0} hour', u'{0} hours',
                            row.hours_since_created).format(
                                                row.hours_since_created)
        else:
            # L10n: first argument is number of days
            r = _(u'%d days') % row.days_since_created
        return jinja2.escape(r)

    def render_flags(self, row):
        if row.admin_review:
            # TODO(Kumar) display Admin Review on hover
            return u'<div class="app-icon ed-sprite-admin-review"></div>'
        else:
            return ''

    def _explode_concat(self, value):
        """Returns list of IDs in a MySQL GROUP_CONCAT(field) result."""
        return [int(i) for i in value.split(',')]
