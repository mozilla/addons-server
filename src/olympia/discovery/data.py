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
        # 'Bokeh Beta' theme.
        DiscoItem(
            addon_id=42019, type=amo.ADDON_PERSONA),

        # Privacy Badger
        DiscoItem(
            addon_id=506646,
            heading=_(u'Stop sneaky trackers {start_sub_heading}'
                      u'with {addon_name}{end_sub_heading}'),
            description=string_concat(
                '<blockquote>',
                _(u' Block invisible trackers and spying ads that follow you '
                  u'around the web.'),
                '</blockquote>')),

        # Tabliss
        DiscoItem(
            addon_id=850407,
            heading=_(u'Customize new tab pages {start_sub_heading}with '
                      u'{addon_name} {end_sub_heading}'),
            description=string_concat(
                '<blockquote>',
                _(u'Enjoy a beautiful new page with customizable backgrounds, '
                  u'local weather info, and more.'),
                '</blockquote>')),

        # 'Foggy Dawn' theme
        DiscoItem(
            addon_id=553386, type=amo.ADDON_PERSONA,
            addon_name='Foggy Dawn'),

        # To Google Translate
        DiscoItem(
            addon_id=445852,
            heading=_(u'Translate easily {start_sub_heading}'
                      u'with {addon_name}{end_sub_heading}'),
            description=string_concat(
                '<blockquote>',
                _(u'Highlight any text, right-click, and translate '
                  u'instantly.'),
                '</blockquote>')),

        # Image Search Options
        DiscoItem(
            addon_id=93451,
            heading=_(u'Search Images {start_sub_heading}with {addon_name}'
                      u'{end_sub_heading}'),
            description=string_concat(
                '<blockquote>',
                _(u'Perform reverse image searches from an array of engines.'),
                '</blockquote>')),

        # 'Sakura Blossoms & Birds' theme.
        DiscoItem(
            addon_id=482976, type=amo.ADDON_PERSONA),
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
