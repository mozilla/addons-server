from django.utils import translation

from mock import Mock

from olympia.amo.tests.test_helpers import render


# Those tests don't need database, so we don't use pytest.mark.django_db.


def test_showing_helper():
    translation.activate('en-US')
    tpl = "{{ showing(query, pager) }}"
    pager = Mock()
    pager.start_index = lambda: 1
    pager.end_index = lambda: 20
    pager.paginator.count = 1000
    context = {'pager': pager}

    context['query'] = ''
    assert render(tpl, context) == 'Showing 1 - 20 of 1000 results'

    context['query'] = 'foobar'
    assert (
        render(tpl, context)
        == 'Showing 1 - 20 of 1000 results for <strong>foobar</strong>'
    )


def test_showing_helper_xss():
    translation.activate('en-US')
    tpl = "{{ showing(query, pager) }}"
    pager = Mock()
    pager.start_index = lambda: 1
    pager.end_index = lambda: 20
    pager.paginator.count = 1000
    context = {'pager': pager}

    context['query'] = '<script>alert(42)</script>'
    assert (
        render(tpl, context) == 'Showing 1 - 20 of 1000 results for <strong>'
        '&lt;script&gt;alert(42)&lt;/script&gt;</strong>'
    )
