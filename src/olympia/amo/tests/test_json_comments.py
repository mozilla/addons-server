from .. import json_comments


def test_remove_comments():
    assert (
        json_comments.remove_comments('{"foo": "bar", // comment\n"1": "2"}')
        == '{"foo": "bar", \n"1": "2"}'
    )
    assert (
        json_comments.remove_comments('["foo", "//inside \\"", // "2"\n"1"]')
        == '["foo", "//inside \\"", \n"1"]'
    )
    assert (
        json_comments.remove_comments('{"foo": "bar", /* comment */\n"1": "2"}')
        == '{"foo": "bar", \n"1": "2"}'
    )
    assert (
        json_comments.remove_comments('["foo", "/*inside\n*/ \\"", /* 2 */\n"1"]')
        == '["foo", "/*inside\n*/ \\"", \n"1"]'
    )
