from defusedxml import minidom
from defusedxml.common import DefusedXmlException
from xml.parsers.expat import ExpatError

from django.utils.translation import ugettext

from olympia import amo
from olympia.files.utils import RDFExtractor, SafeZip, get_file


def insert_validation_message(results, type_='error', message='', msg_id='',
                              compatibility_type=None, description=None):

    if description is None:
        description = []

    results['messages'].insert(0, {
        'tier': 1,
        'type': type_,
        'id': ['validation', 'messages', msg_id],
        'message': message,
        'description': description,
        'compatibility_type': compatibility_type,
    })
    # Need to increment 'errors' or 'warnings' count, so add an extra 's' after
    # the type_ to increment the right entry.
    results['{}s'.format(type_)] += 1
    results['success'] = not results['errors']


def annotate_legacy_addon_restrictions(path, results, parsed_data, error=True):
    """
    Annotate validation results to restrict uploads of legacy
    (non-webextension) add-ons.
    """
    # We can be broad here. Search plugins are not validated through this
    # path and as of right now (Jan 2019) there aren't any legacy type
    # add-ons allowed to submit anymore.
    msg = ugettext(
        u'Legacy extensions are no longer supported in Firefox.')

    description = ugettext(
        u'Add-ons for Thunderbird and SeaMonkey are now listed and '
        u'maintained on addons.thunderbird.net. You can use the same '
        u'account to update your add-ons on the new site.')

    # `parsed_data` only contains the most minimal amount of data because
    # we aren't in the right context. Let's explicitly fetch the add-ons
    # apps so that we can adjust the messaging to the user.
    xpi = get_file(path)
    extractor = RDFExtractor(SafeZip(xpi))

    targets_thunderbird_or_seamonkey = False
    thunderbird_or_seamonkey = {amo.THUNDERBIRD.guid, amo.SEAMONKEY.guid}

    for ctx in extractor.rdf.objects(None, extractor.uri('targetApplication')):
        if extractor.find('id', ctx) in thunderbird_or_seamonkey:
            targets_thunderbird_or_seamonkey = True

    description = description if targets_thunderbird_or_seamonkey else []

    insert_validation_message(
        results, type_='error' if error else 'warning',
        message=msg, description=description,
        msg_id='legacy_addons_unsupported')


def annotate_webext_incompatibilities(results, file_, addon, version_string,
                                      channel):
    """Check for WebExtension upgrades or downgrades.

    We avoid developers to downgrade their webextension to a XUL add-on
    at any cost and warn in case of an upgrade from XUL add-on to a
    WebExtension.

    Firefox doesn't support a downgrade.

    See https://github.com/mozilla/addons-server/issues/3061 and
    https://github.com/mozilla/addons-server/issues/3082 for more details.
    """
    from .utils import find_previous_version

    previous_version = find_previous_version(
        addon, file_, version_string, channel)

    if not previous_version:
        return results

    is_webextension = results['metadata'].get('is_webextension', False)
    was_webextension = previous_version and previous_version.is_webextension

    if is_webextension and not was_webextension:
        results['is_upgrade_to_webextension'] = True

        msg = ugettext(
            'We allow and encourage an upgrade but you cannot reverse '
            'this process. Once your users have the WebExtension '
            'installed, they will not be able to install a legacy add-on.')

        insert_validation_message(
            results, type_='warning', message=msg, msg_id='webext_upgrade')


def annotate_search_plugin_restriction(results, file_path, channel):
    """
    Annotate validation results to restrict uploads of OpenSearch plugins

    https://github.com/mozilla/addons-server/issues/12462

    Once this has settled for a while we may want to merge this with
    `annotate_legacy_addon_restrictions`
    """
    if not file_path.endswith('.xml'):
        return

    # We can be broad here. Search plugins are not validated through this
    # path and as of right now (Jan 2019) there aren't any legacy type
    # add-ons allowed to submit anymore.
    msg = ugettext(
        u'Open Search add-ons are {blog_link_open}no longer supported on AMO'
        u'{blog_link_close}. You can create a {doc_link_open}search extension '
        u'instead{doc_link_close}.').format(
            blog_link_open=(
                '<a href="https://blog.mozilla.org/addons/2019/10/15/'
                'search-engine-add-ons-to-be-removed-from-addons-mozilla-org/">'),
            blog_link_close='</a>',
            doc_link_open=(
                '<a href="https://developer.mozilla.org/docs/Mozilla/'
                'Add-ons/WebExtensions/Your_first_WebExtension">'),
            doc_link_close='</a>')

    insert_validation_message(
        results, type_='error', message=msg, msg_id='legacy_addons_unsupported')
