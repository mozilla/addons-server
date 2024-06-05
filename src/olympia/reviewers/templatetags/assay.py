from django import template

register = template.Library()

@register.simple_tag
def assay_url(addon_guid, version, file=None):
    url = f'vscode://mozilla.assay/review/{addon_guid}/{version}'
    if file:
        url = f'{url}?path={file}'
    return url