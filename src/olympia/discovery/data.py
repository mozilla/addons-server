# -*- coding: utf-8 -*-
from django.utils.translation import string_concat, ugettext_lazy as _


class DiscoItem(object):
    def __init__(self, *args, **kwargs):
        self.addon_id = kwargs.get('addon_id')
        self.addon_name = kwargs.get('addon_name')
        self.heading = kwargs.get('heading')
        self.description = kwargs.get('description')


# At the moment the disco pane items are hardcoded in this file in the repos,
# which allows us to integrate in our translation workflow easily. Add-on ids
# are used instead of slugs to prevent any accidental replacement of a deleted
# add-on by another.
discopane_items = [
    # 'Japanese Tattoo' theme.
    DiscoItem(addon_id=18781),

    # Bulk Media Downloader
    DiscoItem(
        addon_id=728674,
        heading=_(u'Download media {start_sub_heading}with {addon_name}'
                  u'{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'Manage massive audio, video, and image downloads with this '
              u'lightweight tool.'),
            '</blockquote>')),

    # uBlock Origin
    DiscoItem(
        addon_id=607454,
        heading=_(u'Block ads {start_sub_heading}with {addon_name}'
                  u'{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'A lightweight and effective ad blocker. uBlock Origin '
              u'enforces thousands of content filters without chewing up a '
              u'bunch of memory.'),
            '</blockquote>')),

    # 'Two Little Birds' theme.
    DiscoItem(addon_id=153659, addon_name='Two Little Birds'),

    # Awesome Screenshot Plus
    DiscoItem(
        addon_id=287841,
        heading=_(u'Take screenshots {start_sub_heading}with '
                  u'{addon_name}{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'More than just screenshots, Awesome Screenshot Plus lets you '
              u'annotate images with text and graphics. Storing and sharing '
              u'files is a breeze.'),
            '</blockquote>')),

    # Emoji Keyboard
    DiscoItem(
        addon_id=674732,
        heading=_(u'Emoji expression {start_sub_heading}with {addon_name}'
                  u'{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'Dozens of amazing emojis for every occasion—always just one '
              u'click away.'),
            '</blockquote>')),

    # 'Giz Gaz' theme.
    DiscoItem(addon_id=292930, addon_name='Giz Gaz'),
]
