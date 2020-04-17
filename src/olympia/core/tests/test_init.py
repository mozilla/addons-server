from olympia import core


def test_override_remote_addr():
    original = core.get_remote_addr()

    with core.override_remote_addr('some other value'):
        assert core.get_remote_addr() == 'some other value'

    assert core.get_remote_addr() == original
