from amo.messages import _make_message

def test_xss():

    title = "<script>alert(1)</script>"
    message = "<script>alert(2)</script>"

    r = _make_message(title)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r
    r = _make_message(None, message)
    assert "&lt;script&gt;alert(2)&lt;/script&gt;" in r

    r = _make_message(title, title_safe=True)
    assert "<script>alert(1)</script>" in r
    r = _make_message(None, message, message_safe=True)
    assert "<script>alert(2)</script>" in r

    # Make sure safe flags are independent
    r = _make_message(title, message_safe=True)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r
    r = _make_message(None, message, title_safe=True)
    assert "&lt;script&gt;alert(2)&lt;/script&gt;" in r
