from django import template
from django.conf import settings

register = template.Library()


@register.simple_tag
def code_manager_url(page, addon_id, version_id, base_version_id=None, file=None):
    # Always return URLs in en-US because the Code Manager is not localized.
    url = f'{settings.CODE_MANAGER_URL}/en-US'
    if page == 'browse':
        url = f'{url}/browse/{addon_id}/versions/{version_id}/'
    else:
        url = '{}/compare/{}/versions/{}...{}/'.format(
            url, addon_id, base_version_id, version_id
        )
    if file:
        url = f'{url}?path={file}'
    return url
