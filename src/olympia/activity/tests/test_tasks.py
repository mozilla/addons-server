import mock

from olympia.activity.tasks import process_email


@mock.patch('olympia.activity.tasks.add_email_to_activity_log_wrapper')
def test_process_email(_mock):
    # MessageId not in the message we pass to process_email should fail too.
    process_email({})
    assert _mock.call_count == 0
    message = {'MessageId': 'Dave'}
    process_email(message)
    assert _mock.call_count == 1
    # don't try to process the same message twice
    process_email(message)
    assert _mock.call_count == 1
