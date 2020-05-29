from django import template
from django.conf import settings

register = template.Library()


@register.simple_tag
def code_manager_url(
        page, addon_id, version_id, compare_version_id=None, file=None):
    # Always return URLs in en-US because the Code Manager is not localized.
    url = '{}/en-US'.format(settings.CODE_MANAGER_URL)
    if page == 'browse':
        url = '{}/browse/{}/versions/{}/'.format(url, addon_id, version_id)
    else:
        url = '{}/compare/{}/versions/{}...{}/'.format(
            url, addon_id, compare_version_id, version_id)
    if file is not None:
        url = '{}?path={}'.format(url, file)
    return url
