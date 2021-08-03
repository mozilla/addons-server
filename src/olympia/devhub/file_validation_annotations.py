from django.utils.translation import gettext


def insert_validation_message(
    results,
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
