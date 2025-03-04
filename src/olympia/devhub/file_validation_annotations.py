from django.utils.translation import gettext

import waffle

from olympia.versions.models import DeniedInstallOrigin


def insert_validation_message(
    results,
    *,
    type_='error',
    message='',
    msg_id='',
    compatibility_type=None,
    description=None,
):
    if description is None:
        description = []

    results['messages'].insert(
        0,
        {
            'tier': 1,
            'type': type_,
            'id': ['validation', 'messages', msg_id],
            'message': message,
            'description': description,
            'compatibility_type': compatibility_type,
            # Indicate that it's an extra message not coming from the linter:
            # our JavaScript has some logic to display a checklist if there are
            # linter warnings, so we want these custom messages we're inserting
            # to be excluded from that.
            'extra': True,
        },
    )
    # Need to increment 'errors' or 'warnings' count, so add an extra 's' after
    # the type_ to increment the right entry.
    results[f'{type_}s'] += 1
    results['success'] = not results['errors']


def annotate_search_plugin_restriction(results, file_path, channel):
    """
    Annotate validation results to restrict uploads of OpenSearch plugins

    https://github.com/mozilla/addons-server/issues/12462
    """
    if not file_path.endswith('.xml'):
        return

    # We can be broad here. Search plugins are not validated through this
    # path and as of right now (Jan 2019) there aren't any legacy type
    # add-ons allowed to submit anymore.
    msg = gettext(
        'Open Search add-ons are {blog_link_open}no longer supported on AMO'
        '{blog_link_close}. You can create a {doc_link_open}search extension '
        'instead{doc_link_close}.'
    ).format(
        blog_link_open=(
            '<a href="https://blog.mozilla.org/addons/2019/10/15/'
            'search-engine-add-ons-to-be-removed-from-addons-mozilla-org/'
            '">'
        ),
        blog_link_close='</a>',
        doc_link_open=(
            '<a href="https://developer.mozilla.org/docs/Mozilla/Add-ons/'
            'WebExtensions/manifest.json/chrome_settings_overrides">'
        ),
        doc_link_close='</a>',
    )

    insert_validation_message(
        results, type_='error', message=msg, msg_id='opensearch_unsupported'
    )


def annotate_validation_results(*, results, parsed_data):
    """Annotate validation results with potential add-on restrictions like
    denied origins."""
    if waffle.switch_is_active('record-install-origins'):
        if install_origins := parsed_data.get('install_origins'):
            denied_origins = sorted(
                DeniedInstallOrigin.find_denied_origins(install_origins)
            )
            for origin in denied_origins:
                insert_validation_message(
                    results,
                    message=str(DeniedInstallOrigin.ERROR_MESSAGE).format(
                        origin=origin
                    ),
                )
    add_manifest_version_messages(results=results)
    return results


def add_manifest_version_messages(*, results):
    mv = results.get('metadata', {}).get('manifestVersion')
    if mv != 3:
        return
    if 'messages' not in results:
        results['messages'] = []
    enable_mv3_submissions = waffle.switch_is_active('enable-mv3-submissions')
    if not enable_mv3_submissions:
        msg = gettext(
            'Manifest V3 is currently not supported for upload. '
            '{start_href}Read more about the support timeline{end_href}.'
        )
        url = 'https://blog.mozilla.org/addons/2021/05/27/manifest-v3-update/'
        start_href = f'<a href="{url}" target="_blank" rel="noopener">'

        new_error_message = msg.format(start_href=start_href, end_href='</a>')
        for index, message in enumerate(results['messages']):
            if message.get('instancePath') == '/manifest_version':
                # if we find the linter manifest_version=3 warning, replace it
                results['messages'][index]['message'] = new_error_message
                break
        else:
            # otherwise insert a new error at the start of the errors
            insert_validation_message(
                results, message=new_error_message, msg_id='mv3_not_supported_yet'
            )
