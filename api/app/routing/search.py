"""Multimodal routing with bounded labels instead of Cartesian transfers."""
from api.app.routing.round_search import scan_routes


def best_routes(indexes, origins, destinations, limit, counts=None, routing_mode="fewest_transfers"):
    if counts is None:
        counts = {}
    counts.update(direct=0, one_transfer=0, two_transfers=0)
    if limit <= 0:
        return []
    return scan_routes(indexes, tuple(dict.fromkeys(origins)),
                       tuple(dict.fromkeys(destinations)), limit, counts, routing_mode)
