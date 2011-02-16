import os

from django.conf import settings
import django_tables as tables
import jinja2
from jingo import register
from tower import ugettext_lazy as _, ungettext as ngettext

import amo
from editors.models import (ViewPendingQueue, ViewFullReviewQueue,
                            ViewPreliminaryQueue)
from editors.sql_table import SQLTable
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


class EditorQueueTable(SQLTable):
    addon_name = tables.Column(verbose_name=_(u'Addon'))
    addon_type_id = tables.Column(verbose_name=_(u'Type'))
    waiting_time_days = tables.Column(verbose_name=_(u'Waiting Time'))
    flags = tables.Column(verbose_name=_(u'Flags'), sortable=False)
    applications = tables.Column(verbose_name=_(u'Applications'),
                                 sortable=False)
    additional_info = tables.Column(verbose_name=_(u'Additional Information'),
                                    sortable=False)

    def render_addon_name(self, row):
        url = '%s?num=%s' % (reverse('editors.review',
                                     args=[row.latest_version_id]),
                             self.item_number)
        self.item_number += 1
        return u'<a href="%s">%s %s</a>' % (
                    url, jinja2.escape(row.addon_name),
                    jinja2.escape(row.latest_version))

    def render_addon_type_id(self, row):
        return amo.ADDON_TYPE[row.addon_type_id]

    def render_additional_info(self, row):
        if row.is_site_specific:
            r = _(u'Site Specific')
        elif (len(row.file_platform_ids) == 1
              and row.file_platform_ids != [amo.PLATFORM_ALL.id]):
            k = row.file_platform_ids[0]
            # L10n: first argument is the platform such as Linux, Mac OS X
            r = _(u'{0} only').format(amo.PLATFORMS[k].name)
        else:
            r = ''
        return jinja2.escape(r)

    def render_applications(self, row):
        # TODO(Kumar) show supported version ranges on hover (if still needed)
        icon = u'<div class="app-icon ed-sprite-%s" title="%s"></div>'
        return u''.join([icon % (amo.APPS_ALL[i].short, amo.APPS_ALL[i].pretty)
                         for i in row.application_ids])

    def render_flags(self, row):
        if not row.admin_review:
            return ''
        return (u'<div class="app-icon ed-sprite-admin-review" title="%s">'
                u'</div>' % _('Admin Review'))

    def render_waiting_time_days(self, row):
        if row.waiting_time_days == 0:
            # L10n: first argument is number of hours
            r = ngettext(u'{0} hour', u'{0} hours',
                            row.waiting_time_hours).format(
                                                row.waiting_time_hours)
        else:
            # L10n: first argument is number of days
            r = ngettext(u'{0} day', u'{0} days',
                         row.waiting_time_days).format(
                                                row.waiting_time_days)
        return jinja2.escape(r)

    def set_page(self, page):
        self.item_number = page.start_index()

    class Meta:
        sortable = True
        columns = ['addon_name', 'addon_type_id', 'waiting_time_days',
                   'flags', 'applications', 'additional_info']


class ViewPendingQueueTable(EditorQueueTable):

    class Meta(EditorQueueTable.Meta):
        model = ViewPendingQueue


class ViewFullReviewQueueTable(EditorQueueTable):

    class Meta(EditorQueueTable.Meta):
        model = ViewFullReviewQueue


class ViewPreliminaryQueueTable(EditorQueueTable):

    class Meta(EditorQueueTable.Meta):
        model = ViewPreliminaryQueue
