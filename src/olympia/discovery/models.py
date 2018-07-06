from django.db import models
from django.utils.html import conditional_escape, format_html
from django.utils.translation import ugettext

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.models import ModelBase
from olympia.amo.templatetags.jinja_helpers import absolutify


class DiscoveryItem(ModelBase):
    addon = models.OneToOneField(
        Addon, on_delete=models.CASCADE,
        help_text='Add-on id this item will point to (If you do not know the '
                  'id, paste the slug instead and it will be transformed '
                  'automatically for you. If you have access to the add-on '
                  'admin page, you can use the magnifying glass to see '
                  'all available add-ons.')
    custom_addon_name = models.CharField(
        max_length=255, blank=True,
        help_text='Custom add-on name, if needed for space constraints. '
                  'Will be used in the heading if present, but will *not* be '
                  'translated.')
    custom_heading = models.CharField(
        max_length=255, blank=True,
        help_text='Short text used in the header. Can contain the following '
                  'special tags: {start_sub_heading}, {addon_name}, '
                  '{end_sub_heading}. Will be translated.')
    custom_description = models.TextField(
        blank=True, help_text='Longer text used to describe an add-on. Should '
                              'not contain any HTML or special tags. Will be '
                              'translated.')

    def __unicode__(self):
        return unicode(self.addon)

    @property
    def heading(self):
        """
        Return item heading (translated, including HTML) ready to be returned
        by the disco pane API.
        """
        addon_name = unicode(self.custom_addon_name or self.addon.name)
        authors = u', '.join(
            author.name for author in self.addon.listed_authors)
        url = absolutify(self.addon.get_url_path())

        # addons-frontend will add target and rel attributes to the <a> link.
        # Note: The translated "by" in the middle of both strings is
        # unfortunate, but the full strings are too opaque/dangerous to be
        # handled by translators, since they are just HTML and parameters.
        if self.custom_heading:
            addon_link = format_html(
                u'<a href="{0}">{1} {2} {3}</a>',
                url, addon_name, ugettext(u'by'), authors)

            value = conditional_escape(ugettext(self.custom_heading)).replace(
                u'{start_sub_heading}', u'<span>').replace(
                u'{end_sub_heading}', u'</span>').replace(
                u'{addon_name}', addon_link)
        else:
            value = format_html(
                u'{0} <span>{1} <a href="{2}">{3}</a></span>',
                addon_name, ugettext(u'by'), url, authors)
        return value

    @property
    def description(self):
        """
        Return item description (translated, including HTML) ready to be
        returned by the disco pane API.
        """
        if self.custom_description:
            value = ugettext(self.custom_description)
        else:
            addon = self.addon
            if addon.type == amo.ADDON_EXTENSION and addon.summary:
                value = addon.summary
            elif addon.type == amo.ADDON_PERSONA and addon.description:
                value = addon.description
            else:
                value = u''
        return format_html(
            u'<blockquote>{}</blockquote>', value) if value else value
