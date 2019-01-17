import waffle

from defusedxml import minidom
from defusedxml.common import DefusedXmlException
from xml.parsers.expat import ExpatError

from django.utils.translation import ugettext
from django.utils.encoding import force_bytes

from olympia import amo
from olympia.lib.akismet.models import AkismetReport
from olympia.versions.compare import version_int


def insert_validation_message(results, type_='error', message='', msg_id='',
                              compatibility_type=None, description=None):

    if description is None:
        description = []

    messages = results['messages']
    messages.insert(0, {
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


def annotate_legacy_addon_restrictions(results, is_new_upload):
    """
    Annotate validation results to restrict uploads of legacy
    (non-webextension) add-ons if specific conditions are met.
    """
    metadata = results.get('metadata', {})
    is_webextension = metadata.get('is_webextension') is True

    if is_webextension:
        # If we're dealing with a webextension, return early as the whole
        # function is supposed to only care about legacy extensions.
        return results

    target_apps = metadata.get('applications', {})
    max_target_firefox_version = max(
        version_int(target_apps.get('firefox', {}).get('max', '')),
        version_int(target_apps.get('android', {}).get('max', ''))
    )

    is_extension_or_complete_theme = (
        # Note: annoyingly, `detected_type` is at the root level, not under
        # `metadata`.
        results.get('detected_type') in ('theme', 'extension'))
    is_targeting_firefoxes_only = target_apps and (
        set(target_apps.keys()).intersection(('firefox', 'android')) ==
        set(target_apps.keys())
    )
    is_targeting_thunderbird_or_seamonkey_only = target_apps and (
        set(target_apps.keys()).intersection(('thunderbird', 'seamonkey')) ==
        set(target_apps.keys())
    )
    is_targeting_firefox_lower_than_53_only = (
        metadata.get('strict_compatibility') is True and
        # version_int('') is actually 200100. If strict compatibility is true,
        # the validator should have complained about the non-existant max
        # version, but it doesn't hurt to check that the value is sane anyway.
        max_target_firefox_version > 200100 and
        max_target_firefox_version < 53000000000000
    )
    is_targeting_firefox_higher_or_equal_than_57 = (
        max_target_firefox_version >= 57000000000000 and
        max_target_firefox_version < 99000000000000)

    # Thunderbird/Seamonkey only add-ons are moving to addons.thunderbird.net.
    if (is_targeting_thunderbird_or_seamonkey_only):
        msg = ugettext(
            u'Add-ons for Thunderbird and SeaMonkey are now listed and '
            u'maintained on addons.thunderbird.net. You can use the same '
            u'account to update your add-ons on the new site.')

        insert_validation_message(
            results, message=msg, msg_id='thunderbird_and_seamonkey_migration')

    # Legacy add-ons are no longer supported on AMO (if waffle is enabled).
    elif (is_extension_or_complete_theme and
            waffle.switch_is_active('disallow-legacy-submissions')):
        msg = ugettext(
            u'Legacy extensions are no longer supported in Firefox.')

        insert_validation_message(
            results, message=msg, msg_id='legacy_addons_unsupported')

    # New legacy add-ons targeting Firefox only must target Firefox 53 or
    # lower, strictly. Extensions targeting multiple other apps are exempt from
    # this.
    elif (is_new_upload and
            is_extension_or_complete_theme and
            is_targeting_firefoxes_only and
            not is_targeting_firefox_lower_than_53_only):

        msg = ugettext(
            u'Starting with Firefox 53, new add-ons on this site can '
            u'only be WebExtensions.')

        insert_validation_message(
            results, message=msg, msg_id='legacy_addons_restricted')

    # All legacy add-ons (new or upgrades) targeting Firefox must target
    # Firefox 56.* or lower, even if they target multiple apps.
    elif (is_extension_or_complete_theme and
            is_targeting_firefox_higher_or_equal_than_57):
        # Note: legacy add-ons targeting '*' (which is the default for sdk
        # add-ons) are excluded from this error, and instead are silently
        # rewritten as supporting '56.*' in the manifest parsing code.
        msg = ugettext(
            u'Legacy add-ons are not compatible with Firefox 57 or higher. '
            u'Use a maxVersion of 56.* or lower.')

        insert_validation_message(
            results, message=msg, msg_id='legacy_addons_max_version')

    return results


def annotate_legacy_langpack_restriction(results):
    """
    Annotate validation results to restrict uploads of legacy langpacks.
    See https://github.com/mozilla/addons-linter/issues/1985 for more details.
    """
    if not waffle.switch_is_active('disallow-legacy-langpacks'):
        return

    metadata = results.get('metadata', {})

    is_webextension = metadata.get('is_webextension') is True
    target_apps = metadata.get('applications', {})

    is_langpack = results.get('detected_type') == 'langpack'
    is_targeting_firefoxes_only = (
        set(target_apps.keys()).intersection(('firefox', 'android')) ==
        set(target_apps.keys())
    )

    if not is_webextension and is_langpack and is_targeting_firefoxes_only:
        link = (
            'https://developer.mozilla.org/Add-ons/WebExtensions/'
            'manifest.json')
        msg = ugettext(
            u'Legacy language packs for Firefox are no longer supported. '
            u'A WebExtensions install manifest is required. See {mdn_link} '
            u'for more details.')

        insert_validation_message(
            results, message=msg.format(mdn_link=link),
            msg_id='legacy_langpacks_disallowed')

    return results


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

        messages = results['messages']
        messages.insert(0, {
            'tier': 1,
            'type': 'warning',
            'id': ['validation', 'messages', 'webext_upgrade'],
            'message': msg,
            'description': [],
            'compatibility_type': None})
        results['warnings'] += 1
    elif was_webextension and not is_webextension:
        msg = ugettext(
            'You cannot update a WebExtensions add-on with a legacy '
            'add-on. Your users would not be able to use your new version '
            'because Firefox does not support this type of update.')

        messages = results['messages']
        messages.insert(0, {
            'tier': 1,
            'type': ('error' if channel == amo.RELEASE_CHANNEL_LISTED
                     else 'warning'),
            'id': ['validation', 'messages', 'webext_downgrade'],
            'message': msg,
            'description': [],
            'compatibility_type': None})
        if channel == amo.RELEASE_CHANNEL_LISTED:
            results['errors'] += 1
        else:
            results['warnings'] += 1

    return results


def annotate_akismet_spam_check(results, akismet_results):
    msg = ugettext(u'[{field}] The text in the "{field}" field has been '
                   u'flagged as spam.')
    error_if_spam = waffle.switch_is_active('akismet-addon-action')
    for (comment_type, report_result) in akismet_results:
        if error_if_spam and report_result in (
                AkismetReport.MAYBE_SPAM, AkismetReport.DEFINITE_SPAM):
            field = comment_type.split('-')[1]  # drop the "product-"
            insert_validation_message(
                results, message=msg.format(field=field),
                msg_id='akismet_is_spam_%s' % field)


def annotate_search_plugin_validation(results, file_, channel):
    if not file_.current_file_path.endswith('.xml'):
        return

    try:
        # Requires bytes because defusedxml fails to detect
        # unicode strings as filenames.
        # https://gist.github.com/EnTeQuAk/25f99701d8b123f7611acd6ce0d5840b
        dom = minidom.parse(force_bytes(file_.current_file_path))
    except DefusedXmlException:
        url = 'https://pypi.python.org/pypi/defusedxml/0.3#attack-vectors'
        insert_validation_message(
            results,
            message='OpenSearch: XML Security error.',
            description=[
                'The OpenSearch extension could not be parsed due to a '
                'security error in the XML. See {} for more info.'
                .format(url)])
        return
    except ExpatError:
        insert_validation_message(
            results,
            message='OpenSearch: XML Parse Error.',
            description=[
                'The OpenSearch extension could not be parsed due to a syntax '
                'error in the XML.'])
        return

    # Make sure that the root element is OpenSearchDescription.
    if dom.documentElement.tagName != 'OpenSearchDescription':
        insert_validation_message(
            results,
            message='OpenSearch: Invalid Document Root.',
            description=[
                'The root element of the OpenSearch provider is not '
                '"OpenSearchDescription".'])

    # Per bug 617822
    if not dom.documentElement.hasAttribute('xmlns'):
        insert_validation_message(
            results,
            message='OpenSearch: Missing XMLNS attribute.',
            description=[
                'The XML namespace attribute is missing from the '
                'OpenSearch document.'])

    if ('xmlns' not in dom.documentElement.attributes.keys() or
        dom.documentElement.attributes['xmlns'].value not in (
            'http://a9.com/-/spec/opensearch/1.0/',
            'http://a9.com/-/spec/opensearch/1.1/',
            'http://a9.com/-/spec/opensearchdescription/1.1/',
            'http://a9.com/-/spec/opensearchdescription/1.0/')):
        insert_validation_message(
            results,
            message='OpenSearch: Bad XMLNS attribute.',
            description=['The XML namespace attribute contains an value.'])

    # Make sure that there is exactly one ShortName.
    sn = dom.documentElement.getElementsByTagName('ShortName')
    if not sn:
        insert_validation_message(
            results,
            message='OpenSearch: Missing <ShortName> elements.',
            description=[
                'ShortName elements are mandatory OpenSearch provider '
                'elements.'])
    elif len(sn) > 1:
        insert_validation_message(
            results,
            message='OpenSearch: Too many <ShortName> elements.',
            description=[
                'Too many ShortName elements exist in the OpenSearch provider.'
            ]
        )
    else:
        sn_children = sn[0].childNodes
        short_name = 0
        for node in sn_children:
            if node.nodeType == node.TEXT_NODE:
                short_name += len(node.data)
        if short_name > 16:
            insert_validation_message(
                results,
                message='OpenSearch: <ShortName> element too long.',
                description=[
                    'The ShortName element must contains less than seventeen '
                    'characters.'])

    # Make sure that there is exactly one Description.
    if len(dom.documentElement.getElementsByTagName('Description')) != 1:
        insert_validation_message(
            results,
            message='OpenSearch: Invalid number of <Description> elements.',
            description=[
                'There are too many or too few Description elements '
                'in the OpenSearch provider.'])

    # Grab the URLs and make sure that there is at least one.
    urls = dom.documentElement.getElementsByTagName('Url')
    if not urls:
        insert_validation_message(
            results,
            message='OpenSearch: Missing <Url> elements.',
            description=['The OpenSearch provider is missing a Url element.'])

    ref_self_disallowed = (
        channel == amo.RELEASE_CHANNEL_LISTED and
        any(url.hasAttribute('rel') and url.attributes['rel'].value == 'self'
            for url in urls))

    if ref_self_disallowed:
        insert_validation_message(
            results,
            message='OpenSearch: <Url> elements may not be rel=self.',
            description=[
                'Per AMO guidelines, OpenSearch providers cannot '
                "contain <Url /> elements with a 'rel' attribute "
                "pointing to the URL's current location. It must be "
                'removed before posting this provider to AMO.'])

    acceptable_mimes = ('text/html', 'application/xhtml+xml')
    acceptable_urls = [
        u for u in urls if u.hasAttribute('type') and
        u.attributes['type'].value in acceptable_mimes]

    # At least one Url must be text/html
    if not acceptable_urls:
        insert_validation_message(
            results,
            message=(
                'OpenSearch: Missing <Url> element with \'text/html\' type.'),
            description=[
                'OpenSearch providers must have at least one Url '
                'element with a type attribute set to \'text/html\'.'])

    # Make sure that each Url has the require attributes.
    for url in acceptable_urls:
        if url.hasAttribute('rel') and url.attributes['rel'].value == 'self':
            continue

        if url.hasAttribute('method') and \
           url.attributes['method'].value.upper() not in ('GET', 'POST'):
            insert_validation_message(
                results,
                message='OpenSearch: <Url> element with invalid \'method\'.',
                description=[
                    'A Url element in the OpenSearch provider lists a '
                    'method attribute, but the value is not GET or '
                    'POST.'])

        # Test for attribute presence.
        if not url.hasAttribute('template'):
            insert_validation_message(
                results,
                message=(
                    'OpenSearch: <Url> element missing template attribute.'),
                description=[
                    '<Url> elements of OpenSearch providers must '
                    'include a template attribute.'])
        else:
            url_template = url.attributes['template'].value
            if url_template[:4] != 'http':
                insert_validation_message(
                    results,
                    message=(
                        'OpenSearch: `<Url>` element with invalid `template`.'
                    ),
                    description=[
                        'A `<Url>` element in the OpenSearch '
                        'provider lists a template attribute, but '
                        'the value is not a valid HTTP URL.'])

            # Make sure that there is a {searchTerms} placeholder in the
            # URL template.
            found_template = url_template.count('{searchTerms}') > 0

            # If we didn't find it in a simple parse of the template=""
            # attribute, look deeper at the <Param /> elements.
            if not found_template:
                for param in url.getElementsByTagName('Param'):
                    # As long as we're in here and dependent on the
                    # attributes, we'd might as well validate them.
                    attribute_keys = param.attributes.keys()
                    if 'name' not in attribute_keys or \
                       'value' not in attribute_keys:
                        insert_validation_message(
                            results,
                            message=(
                                'OpenSearch: `<Param>` element missing '
                                '\'name/value\'.'),
                            description=[
                                'Param elements in the OpenSearch '
                                'provider must include a name and a '
                                'value attribute.'])

                    param_value = (
                        param.attributes['value'].value if
                        'value' in param.attributes.keys() else '')

                    if param_value.count('{searchTerms}'):
                        found_template = True

            # If the template still hasn't been found...
            if not found_template:
                tpl = url.attributes['template'].value
                insert_validation_message(
                    results,
                    message=(
                        'OpenSearch: <Url> element missing template '
                        'placeholder.'),
                    description=[
                        '`<Url>` elements of OpenSearch providers '
                        'must include a template attribute or specify a '
                        'placeholder with `{searchTerms}`.',
                        'Missing template: %s' % tpl])

    # Make sure there are no updateURL elements
    if dom.getElementsByTagName('updateURL'):
        insert_validation_message(
            results,
            message=(
                'OpenSearch: <updateURL> elements are banned in OpenSearch '
                'providers.'),
            description=[
                'OpenSearch providers may not contain <updateURL> elements.'])
