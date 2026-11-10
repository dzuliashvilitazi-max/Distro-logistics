import pytest
from pydantic import ValidationError

import server

KEYS = {"p256dh": "k", "auth": "a"}


@pytest.mark.parametrize("endpoint", [
    "https://fcm.googleapis.com/fcm/send/abc",
    "https://updates.push.services.mozilla.com/wpush/v2/abc",
])
def test_public_https_push_endpoints_are_accepted(endpoint):
    assert server.PushSubscriptionIn(endpoint=endpoint, keys=KEYS).endpoint == endpoint


@pytest.mark.parametrize("endpoint", [
    "http://fcm.googleapis.com/fcm/send/abc",
    "https://169.254.169.254/latest/meta-data",
    "https://127.0.0.1:8000/api/admin",
    "https://localhost/hook",
    "https://metadata.internal/x",
    "https://intranet/x",
])
def test_internal_or_non_https_push_endpoints_are_rejected(endpoint):
    with pytest.raises(ValidationError):
        server.PushSubscriptionIn(endpoint=endpoint, keys=KEYS)
