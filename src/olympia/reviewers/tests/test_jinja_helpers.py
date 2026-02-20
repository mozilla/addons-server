from olympia.reviewers.templatetags import assay, jinja_helpers


def test_create_an_assay_url():
    assert jinja_helpers.assay_url(
        addon_guid='{guid}', version_string='version', filepath='file.js'
    ) == assay.assay_url(
        addon_guid='{guid}', version_string='version', filepath='file.js'
    )


def test_to_dom_id():
    assert jinja_helpers.to_dom_id('') == ''
    assert jinja_helpers.to_dom_id('123.456.789') == '123_456_789'
