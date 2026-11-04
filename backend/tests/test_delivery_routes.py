import pytest

from delivery_routes import sequence_stops


def test_sequence_stops_uses_optimized_road_order():
    stops = [
        {"order_id": "a", "order_no": "ORD-A"},
        {"order_id": "b", "order_no": "ORD-B"},
        {"order_id": "c", "order_no": "ORD-C"},
    ]
    waypoints = [
        {"waypoint_index": 0},
        {"waypoint_index": 2},
        {"waypoint_index": 1},
        {"waypoint_index": 3},
    ]

    ordered = sequence_stops(stops, waypoints)

    assert [stop["order_id"] for stop in ordered] == ["b", "a", "c"]
    assert [stop["sequence"] for stop in ordered] == [1, 2, 3]
    assert "sequence" not in stops[0]


def test_sequence_stops_rejects_incomplete_route():
    with pytest.raises(ValueError, match="every requested stop"):
        sequence_stops([{"order_id": "a"}], [{"waypoint_index": 0}])
