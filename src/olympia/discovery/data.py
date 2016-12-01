# -*- coding: utf-8 -*-
from django.utils.translation import string_concat, ugettext_lazy as _


class DiscoItem(object):
    def __init__(self, *args, **kwargs):
        self.addon_id = kwargs.get('addon_id')
        self.addon_name = kwargs.get('addon_name')
        self.heading = kwargs.get('heading')
        self.description = kwargs.get('description')

# At the moment the disco pane items are hardcoded in this file in the repos,
# which allows us to integrate in our translation workflow easily.
discopane_items = [
    # Theme: Ice Flower
    DiscoItem(addon_id=265447),

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

    # Awesome Screenshot Plus - Capture, Annotate & More
    DiscoItem(
        addon_id=287841,
        heading=_(u'Take screenshots {start_sub_heading}with {addon_name}'
                  u'{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'So much more than just a screenshot tool, this add-on also '
              u'lets you edit, annotate, and share images.'),
            '</blockquote>')),

    # Theme: Les Eléphants
    DiscoItem(addon_id=754566, addon_name=u'Les Éléphants'),

    # OmniSidebar
    DiscoItem(
        addon_id=296534,
        heading=_(u'Easily access bookmarks {start_sub_heading}with '
                  u'{addon_name}{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'Are you constantly scrolling through your bookmarks? '
              u'Bring your lists into view with a single, simple gesture.'),
            '</blockquote>')),

    # YouTube High Definition
    DiscoItem(
        addon_id=328839,
        heading=_(u'Enhance YouTube {start_sub_heading}with '
                  u'{addon_name}{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'Automatically play YouTube videos in high-def, turn off '
              u'annotations, adjust player size, and many other ways to '
              u'personalize your video-watching experience.'),
            '</blockquote>')),

    # Theme: My Vinyl
    DiscoItem(addon_id=676070, addon_name=u'Owl First Snow'),
]
