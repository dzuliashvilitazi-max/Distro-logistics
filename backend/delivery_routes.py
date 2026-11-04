def sequence_stops(stops: list[dict], waypoints: list[dict]) -> list[dict]:
    if len(waypoints) != len(stops) + 1:
        raise ValueError("Route result does not include every requested stop.")
    sequence = sorted(
        (
            (waypoint["waypoint_index"], index - 1)
            for index, waypoint in enumerate(waypoints)
            if index > 0
        ),
        key=lambda item: item[0],
    )
    ordered_stops = [dict(stops[stop_index]) for _, stop_index in sequence]
    for index, stop in enumerate(ordered_stops, start=1):
        stop["sequence"] = index
    return ordered_stops
