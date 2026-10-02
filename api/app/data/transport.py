"""Public bus line names and transport mode."""
from api.app.schemas.snapshot import Route

def public_line_code(value: str) -> str:
    return value.strip()


def route_mode(route: Route, source: str = '') -> str:
    return 'Tramvay' if route.route_type == 0 or (route.route_type is not None and 900 <= route.route_type <= 906) else 'Otobüs'
