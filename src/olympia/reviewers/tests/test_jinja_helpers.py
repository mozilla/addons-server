import pytest

from olympia.abuse.models import CinderPolicy
from olympia.reviewers.templatetags import assay, jinja_helpers


pytestmark = pytest.mark.django_db


def test_create_an_assay_url():
    assert jinja_helpers.assay_url(
        addon_guid='{guid}', version_string='version', filepath='file.js'
    ) == assay.assay_url(
        addon_guid='{guid}', version_string='version', filepath='file.js'
    )


def test_format_score():
    assert jinja_helpers.format_score(15.1) == '15%'
    assert jinja_helpers.format_score(0) == 'n/a'
    assert jinja_helpers.format_score(-1) == 'n/a'


def test_to_dom_id():
    assert jinja_helpers.to_dom_id('') == ''
    assert jinja_helpers.to_dom_id('123.456.789') == '123_456_789'


def test_render_text_with_input_fields():
    policy = CinderPolicy(name='a', text='Something {THIS} and {<THAT_"}?')
    assert (
        jinja_helpers.render_text_with_input_fields(policy)
        == 'Something <input placeholder="THIS" name="policy-value-None-THIS"> and <'
        'input placeholder="&lt;THAT_&quot;" name="policy-value-None-&lt;THAT_&quot;">?'
    )
