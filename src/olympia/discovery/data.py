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
        # 'Owl First Snow' theme.
        DiscoItem(
            addon_id=676070, type=amo.ADDON_PERSONA,
            addon_name='Owl First Snow'),

        # uBlock Origin
        DiscoItem(
            addon_id=607454,
            heading=_(u'Block ads {start_sub_heading}with {addon_name}'
                      u'{end_sub_heading}'),
            description=string_concat(
                '<blockquote>',
                _(u'A lightweight and effective ad blocker. uBlock Origin '
                  u'enforces thousands of content filters without chewing up '
                  u'a bunch of memory.'),
                '</blockquote>')),

        # LastPass
        DiscoItem(
            addon_id=8542,
            addon_name='LastPass',
            heading=_(u'Manage passwords {start_sub_heading}with {addon_name}'
                      u'{end_sub_heading}'),
            description=string_concat(
                '<blockquote>',
                _(u'Simplify and sync all your various website logins across '
                  u'devices with one password to rule them all.'),
                '</blockquote>')),

        # 'Tiffy01' theme (slug = color-to-color).
        DiscoItem(
            addon_id=290486,
            type=amo.ADDON_PERSONA),

        # Enhancer for YouTube
        DiscoItem(
            addon_id=700308,
            heading=_(u'Improve videos {start_sub_heading}with {addon_name}'
                      u'{end_sub_heading}'),
            description=string_concat(
                '<blockquote>',
                _(u'Enjoy a suite of new YouTube features, like cinema mode, '
                  u'ad blocking, auto-play control, and more.'),
                '</blockquote>')),

        # Emoji Cheatsheet.
        DiscoItem(
            addon_id=511962,
            heading=_(u'Up your emoji game {start_sub_heading}with '
                      u'{addon_name}{end_sub_heading}'),
            description=string_concat(
                '<blockquote>',
                _(u'Dozens of amazing emojis—always a click away.'),
                '</blockquote>')),

        # 'Evil Robots' theme.
        DiscoItem(
            addon_id=21085, type=amo.ADDON_PERSONA, addon_name='Evil Robots'),
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
