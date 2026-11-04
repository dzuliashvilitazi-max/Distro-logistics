import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def test_driver_defaults_to_active_weekday_schedule():
    driver = server.DriverIn(name="Jemali", phone="+995555000001")

    assert driver.active is True
    assert driver.vehicle_plate == ""
    assert driver.working_days == [1, 2, 3, 4, 5]


def test_driver_accepts_plate_and_custom_working_days():
    driver = server.DriverIn(
        name="Nugzari",
        phone="+995555000002",
        vehicle_plate="AB-123-CD",
        working_days=[6, 7],
        active=True,
    )

    assert driver.vehicle_plate == "AB-123-CD"
    assert driver.working_days == [6, 7]


@pytest.mark.parametrize("working_days", [[0], [8], [1, 1], []])
def test_driver_rejects_invalid_working_days(working_days):
    with pytest.raises(ValidationError):
        server.DriverIn(name="Jemali", phone="+995555000001", working_days=working_days)
