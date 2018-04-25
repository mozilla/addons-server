# -*- coding: utf-8 -*-
from django.utils.translation import string_concat, ugettext_lazy as _

from olympia import amo


class DiscoItem(object):
    def __init__(self, *args, **kwargs):
        self.addon_id = kwargs.get('addon_id')
        self.addon_name = kwargs.get('addon_name')
        self.heading = kwargs.get('heading')
        self.description = kwargs.get('description')
        self.type = kwargs.get('type', amo.ADDON_EXTENSION)
        self.is_recommendation = kwargs.get('is_recommendation', False)

    def __repr__(self):
        return 'DiscoItem(%s, %s, %s, %s, %s)' % (
            self.addon_id, self.addon_name, self.heading, self.description,
            self.type)


# At the moment the disco pane items are hardcoded in this file in the repos,
# which allows us to integrate in our translation workflow easily. Add-on ids
# are used instead of slugs to prevent any accidental replacement of a deleted
# add-on by another.
discopane_items = {
    'default': [
        # 'Spring is Here' theme.
        DiscoItem(
            addon_id=368421, type=amo.ADDON_PERSONA,
            addon_name=u'Spring is Here'),

        # Facebook Container
        DiscoItem(
            addon_id=954390,
            heading=_(u'Stop Facebook tracking {start_sub_heading}with '
                      u'{addon_name}{end_sub_heading}'),
            description=string_concat(
                '<blockquote>',
                _(u'Isolate your Facebook identity into a separate '
                  u'"container" that makes it harder for Facebook to track '
                  u'your movements around the web.'),
                '</blockquote>')),

        # Swift Selection Search
        DiscoItem(
            addon_id=587410,
            heading=_(u'Simplify search {start_sub_heading}with '
                      u'{addon_name}{end_sub_heading}'),
            description=string_concat(
                '<blockquote>',
                _(u'Just highlight text on any web page to search the phrase '
                  u'from an array of engines.'),
                '</blockquote>')),

        # 'Dream of Waves' theme
        DiscoItem(
            addon_id=46638, type=amo.ADDON_PERSONA),

        # Ghostery
        DiscoItem(
            addon_id=9609,
            heading=_(u'Ad blocking & privacy protection {start_sub_heading}'
                      u'with {addon_name}{end_sub_heading}'),
            description=string_concat(
                '<blockquote>',
                _(u'A simple set-up lets you take control of the ads you see '
                  u'and how you’re tracked on the internet.'),
                '</blockquote>')),

        # Tree Style Tab
        DiscoItem(
            addon_id=5890,
            heading=_(u'Re-imagine tabs {start_sub_heading}with {addon_name}'
                      u'{end_sub_heading}'),
            description=string_concat(
                '<blockquote>',
                _(u'Do you have a ton of open tabs? Organize them in a tidy '
                  u'sidebar.'),
                '</blockquote>')),

        # 'Space Stars' theme.
        DiscoItem(
            addon_id=211644, type=amo.ADDON_PERSONA,
            addon_name=u'Space Stars'),
    ],
    # China Edition Firefox shows a different selection of add-ons.
    # See discopane_items comments above for more detail on format.
    'china': [
        # 'Vintage Fabric' theme.
        DiscoItem(
            addon_id=492244, type=amo.ADDON_PERSONA,
            addon_name=u'Vintage Fabric'),

        # Video DownloadHelper
        DiscoItem(
            addon_id=3006,
            heading=_(u'Download videos {start_sub_heading}with {addon_name}'
                      u'{end_sub_heading}'),
            description=string_concat(
                '<blockquote>',
                _(u'Works seamlessly with most popular video sites.'),
                '</blockquote>')),

        # New Tab Override
        DiscoItem(
            addon_id=626810,
            addon_name=u'New Tab Override',
            heading=_(u'Tab Customization {start_sub_heading}with {addon_name}'
                      u'{end_sub_heading}'),
            description=string_concat(
                '<blockquote>',
                _(u'Set the page you see every time you open a new tab.'),
                '</blockquote>')),

        # 'Abstract Splash' theme
        DiscoItem(
            addon_id=25725, type=amo.ADDON_PERSONA),

        # Emoji Cheatsheet
        DiscoItem(
            addon_id=511962,
            heading=_(u'Enhance your emoji game {start_sub_heading}with '
                      u'{addon_name}{end_sub_heading}'),
            description=string_concat(
                '<blockquote>',
                _(u'Dozens of amazing emojis for every occasion—always just '
                  u'one click away.'),
                '</blockquote>')),

        # Awesome Screenshot Plus.
        DiscoItem(
            addon_id=287841,
            addon_name=u'Awesome Screenshot Plus',
            heading=_(u'Take screenshots {start_sub_heading}with {addon_name}'
                      u'{end_sub_heading}'),
            description=string_concat(
                '<blockquote>',
                _(u'More than just a basic screenshot tool, Awesome '
                  u'Screenshot Plus lets you annotate images with custom text '
                  u'and graphics, plus the ability to store and share your '
                  u'visuals.'),
                '</blockquote>')),

        # 'Evil Robots' theme.
        DiscoItem(
            addon_id=153659, type=amo.ADDON_PERSONA),
    ],
}
