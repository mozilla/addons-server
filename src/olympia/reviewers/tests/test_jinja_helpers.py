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


def test_toggle_when_action():
    context = {
        'actions': [
            ('action1', {'is_toggle': True}),
            ('action2', {'is_toggle': False}),
            ('action3', {}),
        ]
    }
    assert jinja_helpers.toggle_when_action(context, 'is_toggle') == 'action1'
    assert (
        jinja_helpers.toggle_when_action(context, 'is_toggle', default=False)
        == 'action1'
    )
    assert (
        jinja_helpers.toggle_when_action(context, 'is_toggle', default=True)
        == 'action1 action3'
    )
