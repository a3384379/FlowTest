"""HTTP header names are case insensitive; other parameter names are not."""


def parameter_identity(location: str, name: str) -> tuple[str, str]:
    return location, name.lower() if location == "header" else name
