from django.conf import settings
from django.db import models
from django.http import QueryDict
from django.utils.html import conditional_escape, format_html
from django.utils.translation import ugettext

from olympia import amo
from olympia.addons.models import Addon, update_search_index
from olympia.amo.models import ModelBase, OnChangeMixin
from olympia.amo.templatetags.jinja_helpers import absolutify


class DiscoveryItem(OnChangeMixin, ModelBase):
    RECOMMENDED = 'Recommended'
    PENDING_RECOMMENDATION = 'Pending Recommendation'
    NOT_RECOMMENDED = 'Not Recommended'

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
                  'Will be used in the heading if present, but will '
                  '<strong>not</strong> be translated.')
    custom_heading = models.CharField(
        max_length=255, blank=True,
        help_text='Short text used in the header. Can contain the following '
                  'special tags: {start_sub_heading}, {addon_name}, '
                  '{end_sub_heading}. Will be translated. '
                  'Currently *not* visible to the user - #11817')
    custom_description = models.TextField(
        blank=True, help_text='Longer text used to describe an add-on. Should '
                              'not contain any HTML or special tags. Will be '
                              'translated.')
    position = models.PositiveSmallIntegerField(
        default=0, blank=True, db_index=True,
        help_text='Position in the discovery pane when telemetry-aware '
                  'recommendations are off (editorial fallback). '
                  'The lower the number, the higher the item will appear in '
                  'the page. If left blank or if the value is 0, the item '
                  'will not appear unless part of telemetry-aware '
                  'recommendations.')
    position_china = models.PositiveSmallIntegerField(
        default=0, blank=True, db_index=True,
        help_text='Position in the discovery pane in China '
                  '(See position field above).')
    position_override = models.PositiveSmallIntegerField(
        default=0, blank=True, db_index=True,
        help_text='Position in the discovery pane when telemetry-aware '
                  'recommendations are on but we want to override them.'
                  '(See position field above).')
    recommendable = models.BooleanField(
        db_index=True, null=False, default=False,
        help_text="Should this add-on's versions be recommended. When enabled "
                  'new versions will be reviewed for recommended status.')

    def __str__(self):
        return str(self.addon)

    def build_querystring(self):
        qs = QueryDict(mutable=True)
        qs.update({
            'utm_source': 'discovery.%s' % settings.DOMAIN,
            'utm_medium': 'firefox-browser',
            'utm_content': 'discopane-entry-link',
            'src': 'api',
        })
        return qs.urlencode()

    def _build_heading(self, html=False):
        addon_name = str(self.custom_addon_name or self.addon.name)
        custom_heading = ugettext(
            self.custom_heading) if self.custom_heading else None

        if html:
            authors = ', '.join(
                author.name for author in self.addon.listed_authors)
            url = absolutify(self.addon.get_url_path())
            # addons-frontend will add target and rel attributes to the <a>
            # link. Note: The translated "by" in the middle of both strings is
            # unfortunate, but the full strings are too opaque/dangerous to be
            # handled by translators, since they are just HTML and parameters.
            if self.custom_heading:
                addon_link = format_html(
                    # The query string should not be encoded twice, so we add
                    # it to the template first, via '%'.
                    '<a href="{0}?%(query)s">{1} {2} {3}</a>' % {
                        'query': self.build_querystring()},
                    url, addon_name, ugettext('by'), authors)

                value = conditional_escape(custom_heading).replace(
                    '{start_sub_heading}', '<span>').replace(
                    '{end_sub_heading}', '</span>').replace(
                    '{addon_name}', addon_link)
            else:
                value = format_html(
                    # The query string should not be encoded twice, so we add
                    # it to the template first, via '%'.
                    '{0} <span>{1} <a href="{2}?%(query)s">{3}</a></span>' % {
                        'query': self.build_querystring()},
                    addon_name, ugettext('by'), url, authors)
        else:
            if self.custom_heading:
                value = custom_heading.replace(
                    '{start_sub_heading}', '').replace(
                    '{end_sub_heading}', '').replace(
                    '{addon_name}', addon_name)
            else:
                value = addon_name
        return value

    def _build_description(self, html=False):
        if self.custom_description:
            value = ugettext(self.custom_description)
        else:
            addon = self.addon
            if addon.type == amo.ADDON_EXTENSION and addon.summary:
                value = addon.summary
            else:
                value = u''
        if html:
            return format_html(
                u'<blockquote>{}</blockquote>', value) if value else value
        else:
            return value

    @property
    def heading(self):
        """
        Return item heading (translated, including HTML) ready to be returned
        by the disco pane API.
        """
        return self._build_heading(html=True)

    @property
    def heading_text(self):
        """
        Return item heading (translated, but not including HTML) ready to be
        returned by the disco pane API.

        It may differ from the HTML version slightly and contain less
        information, leaving clients the choice to use extra data returned by
        the API or not.
        """
        return self._build_heading(html=False)

    @property
    def description(self):
        """
        Return item description (translated, including HTML) ready to be
        returned by the disco pane API.
        """
        return self._build_description(html=True)

    @property
    def description_text(self):
        """
        Return item description (translated, but not including HTML) ready to
        be returned by the disco pane API.
        """
        return self._build_description(html=False)

    @property
    def recommended_status(self):
        return (
            self.RECOMMENDED if (
                self.recommendable and
                self.addon.current_version and
                self.addon.current_version.recommendation_approved) else
            self.PENDING_RECOMMENDATION if self.recommendable else
            self.NOT_RECOMMENDED)

    def primary_hero_shelf(self):
        return (self.primaryhero.enabled if hasattr(self, 'primaryhero')
                else None)
    primary_hero_shelf.boolean = True


@DiscoveryItem.on_change
def watch_recommendable_changes(old_attr=None, new_attr=None, instance=None,
                                sender=None, **kwargs):
    if 'recommendable' in old_attr or 'recommendable' in new_attr:
        old_value = old_attr.get('recommendable')
        new_value = new_attr.get('recommendable')
        if old_value != new_value:
            # Update ES because is_recommended depends on it.
            update_search_index(
                sender=sender, instance=instance.addon, **kwargs)
