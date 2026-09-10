from app.importers.contracts import ImportSourceType
from app.importers.document import parse_import_document


def test_imported_credentials_use_secret_references_when_redaction_is_off() -> None:
    _, operations = parse_import_document(
        b"curl -u tester:password -H 'Authorization: Bearer token' https://api.example.test/users",
        ImportSourceType.CURL,
    )

    request = operations[0].request
    assert request.auth_config["password"] == "{{secret.IMPORTED_PASSWORD}}"
    assert request.headers["Authorization"] == "{{secret.IMPORTED_AUTHORIZATION}}"
