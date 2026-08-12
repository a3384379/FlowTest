import hashlib
import json
import re
from typing import Annotated, Any, Literal, Protocol, cast
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, ValidationError

from app.domain.network import OutboundNetworkPolicy

ServiceDisplayName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
]
ServiceKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=2,
        max_length=80,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
    ),
]
ReleaseVersion = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]

MAX_PACT_BYTES = 5 * 1024 * 1024
MAX_PACT_INTERACTIONS = 500
_SENSITIVE_NAME = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|private[_-]?key)",
    re.IGNORECASE,
)
_SAFE_HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,128}$")


class PactContractError(ValueError):
    pass


class PactTransportError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    path: str = Field(min_length=1, max_length=2048, pattern=r"^/[^\s?#]*$")
    query: dict[str, str | list[str]] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: JsonValue = None


class PactResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: int = Field(ge=100, le=599)
    headers: dict[str, str] = Field(default_factory=dict)
    body: JsonValue = None


class PactInteraction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str = Field(min_length=1, max_length=500)
    provider_states: tuple[str, ...] = Field(default=(), max_length=10)
    request: PactRequest
    response: PactResponse


class PactDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    consumer: ServiceDisplayName
    provider: ServiceDisplayName
    specification_version: str = Field(min_length=1, max_length=32)
    interactions: tuple[PactInteraction, ...] = Field(
        min_length=1,
        max_length=MAX_PACT_INTERACTIONS,
    )

    @property
    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json.encode()).hexdigest()


class ProviderInteractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    interaction_index: int = Field(ge=0)
    description: str
    status: Literal["passed", "failed"]
    mismatch_codes: tuple[str, ...] = ()


class ProviderVerificationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["passed", "failed"]
    interaction_results: tuple[ProviderInteractionResult, ...]


class ProviderInteractionVerifier(Protocol):
    async def verify(
        self,
        *,
        target_base_url: str,
        pact: PactDocument,
        network_policy: OutboundNetworkPolicy,
    ) -> ProviderVerificationEvidence: ...


class PactBrokerSource(Protocol):
    async def fetch_pact(
        self,
        *,
        consumer: str,
        provider: str,
        consumer_version: str,
        network_policy: OutboundNetworkPolicy,
    ) -> bytes: ...


def load_pact_document(content: bytes) -> PactDocument:
    if len(content) > MAX_PACT_BYTES:
        raise PactContractError("Pact 文档超过 5 MB 上限")
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PactContractError("Pact 文档必须是有效 UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise PactContractError("Pact 文档根节点必须是对象")
    _validate_tree(value)
    _reject_unsupported_matching(value)
    if value.get("messages") or value.get("synchronousMessages"):
        raise PactContractError("S27 仅支持 HTTP Pact Interaction")
    consumer = _party_name(value, "consumer")
    provider = _party_name(value, "provider")
    interactions_value = value.get("interactions")
    if not isinstance(interactions_value, list) or not interactions_value:
        raise PactContractError("Pact 文档必须包含 HTTP interactions")
    if len(interactions_value) > MAX_PACT_INTERACTIONS:
        raise PactContractError("Pact Interaction 超过 500 条上限")
    metadata = value.get("metadata")
    specification_version = _specification_version(metadata)
    try:
        interactions = tuple(
            _interaction(cast(dict[str, Any], item), index)
            for index, item in enumerate(interactions_value)
            if isinstance(item, dict)
        )
    except ValidationError as error:
        raise PactContractError("Pact Interaction 字段不符合约束") from error
    if len(interactions) != len(interactions_value):
        raise PactContractError("Pact Interaction 必须是对象")
    try:
        return PactDocument(
            consumer=consumer,
            provider=provider,
            specification_version=specification_version,
            interactions=interactions,
        )
    except ValidationError as error:
        raise PactContractError("Pact 文档字段不符合约束") from error


def service_key_for_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")[:50]
    digest = hashlib.sha256(name.strip().encode()).hexdigest()[:12]
    return f"{slug or 'service'}-{digest}"


def normalize_contract_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise PactTransportError(
            "PROVIDER_TARGET_INVALID",
            "Provider/Broker 地址必须是无凭据、Query 和路径的 HTTP/HTTPS Origin",
        )
    return f"{parsed.scheme}://{parsed.netloc}"


def response_mismatch_codes(
    expected: PactResponse,
    *,
    actual_status: int,
    actual_headers: dict[str, str],
    actual_body: JsonValue,
) -> tuple[str, ...]:
    mismatches: list[str] = []
    if actual_status != expected.status:
        mismatches.append("STATUS_MISMATCH")
    normalized_headers = {key.lower(): value for key, value in actual_headers.items()}
    if any(normalized_headers.get(key.lower()) != value for key, value in expected.headers.items()):
        mismatches.append("HEADER_MISMATCH")
    if not _json_matches(expected.body, actual_body):
        mismatches.append("BODY_MISMATCH")
    return tuple(mismatches)


def _interaction(value: dict[str, Any], index: int) -> PactInteraction:
    _reject_unsupported_matching(value)
    description = value.get("description")
    request = value.get("request")
    response = value.get("response")
    if not isinstance(description, str) or not description.strip():
        raise PactContractError(f"Pact Interaction {index + 1} 缺少 description")
    if not isinstance(request, dict) or not isinstance(response, dict):
        raise PactContractError(f"Pact Interaction {index + 1} 缺少 request/response")
    states_value = value.get("providerStates", value.get("providerState", []))
    provider_states = _provider_states(states_value)
    return PactInteraction(
        description=description.strip(),
        provider_states=provider_states,
        request=_request(request),
        response=_response(response),
    )


def _request(value: dict[str, Any]) -> PactRequest:
    _reject_unsupported_matching(value)
    method = str(value.get("method", "")).upper()
    path = value.get("path")
    if not isinstance(path, str):
        raise PactContractError("Pact Request path 无效")
    return PactRequest(
        method=method,
        path=path,
        query=_query(value.get("query")),
        headers=_headers(value.get("headers"), response=False),
        body=_safe_json(value.get("body")),
    )


def _response(value: dict[str, Any]) -> PactResponse:
    _reject_unsupported_matching(value)
    status = value.get("status")
    if not isinstance(status, int):
        raise PactContractError("Pact Response status 无效")
    return PactResponse(
        status=status,
        headers=_headers(value.get("headers"), response=True),
        body=_safe_json(value.get("body")),
    )


def _headers(value: object, *, response: bool) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 64:
        raise PactContractError("Pact Header 必须是最多 64 项的对象")
    result: dict[str, str] = {}
    for raw_name, raw_value in value.items():
        if not isinstance(raw_name, str) or _SAFE_HEADER_NAME.fullmatch(raw_name) is None:
            raise PactContractError("Pact Header 名称无效")
        if _SENSITIVE_NAME.search(raw_name) or (response and raw_name.lower() == "set-cookie"):
            raise PactContractError("Pact 文档不能包含认证、Cookie 或 Secret Header")
        if not isinstance(raw_value, str) or len(raw_value) > 4096:
            raise PactContractError("Pact Header 值必须是长度受限的字符串")
        result[raw_name] = raw_value
    return result


def _query(value: object) -> dict[str, str | list[str]]:
    if value is None:
        return {}
    if isinstance(value, str):
        return _query_string(value)
    if not isinstance(value, dict) or len(value) > 100:
        raise PactContractError("Pact Query 格式无效")
    result: dict[str, str | list[str]] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str) or _SENSITIVE_NAME.search(raw_key):
            raise PactContractError("Pact Query 名称无效或包含 Secret")
        if isinstance(raw_value, str):
            result[raw_key] = raw_value
        elif isinstance(raw_value, list) and all(isinstance(item, str) for item in raw_value):
            result[raw_key] = cast(list[str], raw_value)
        else:
            raise PactContractError("Pact Query 值必须是字符串或字符串列表")
    return result


def _query_string(value: str) -> dict[str, str | list[str]]:
    try:
        pairs = parse_qsl(value, keep_blank_values=True, max_num_fields=100)
    except ValueError as error:
        raise PactContractError("Pact Query 超过 100 项上限") from error
    result: dict[str, str | list[str]] = {}
    for key, item in pairs:
        if _SENSITIVE_NAME.search(key):
            raise PactContractError("Pact Query 不能包含 Secret")
        current = result.get(key)
        if current is None:
            result[key] = item
        elif isinstance(current, list):
            current.append(item)
        else:
            result[key] = [current, item]
    return result


def _reject_unsupported_matching(value: dict[str, Any]) -> None:
    unsupported = {"matchingRules", "generators", "pluginConfiguration"}.intersection(value)
    if unsupported:
        raise PactContractError("S27 Exact Matcher 不接受 Matching Rule、Generator 或 Plugin")


def _provider_states(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value[:200],)
    if not isinstance(value, list) or len(value) > 10:
        raise PactContractError("Provider State 格式无效")
    names: list[str] = []
    for item in value:
        name = item.get("name") if isinstance(item, dict) else item
        if not isinstance(name, str) or not name.strip():
            raise PactContractError("Provider State 名称无效")
        names.append(name.strip()[:200])
    return tuple(names)


def _party_name(value: dict[str, Any], key: str) -> str:
    party = value.get(key)
    name = party.get("name") if isinstance(party, dict) else None
    if not isinstance(name, str) or not name.strip():
        raise PactContractError(f"Pact {key} 名称无效")
    return name.strip()


def _specification_version(metadata: object) -> str:
    if not isinstance(metadata, dict):
        return "3.0.0"
    specification = metadata.get("pactSpecification")
    if not isinstance(specification, dict):
        specification = metadata.get("pact-specification")
    version = specification.get("version") if isinstance(specification, dict) else None
    return str(version or "3.0.0")[:32]


def _safe_json(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return cast(JsonValue, value)
    if isinstance(value, list):
        return [_safe_json(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str) or _SENSITIVE_NAME.search(key):
                raise PactContractError("Pact Body 不能包含 Secret 字段")
            result[key] = _safe_json(item)
        return result
    raise PactContractError("Pact Body 必须是 JSON 值")


def _validate_tree(value: JsonValue, *, depth: int = 0, nodes: list[int] | None = None) -> None:
    counter = nodes if nodes is not None else [0]
    counter[0] += 1
    if depth > 64 or counter[0] > 100_000:
        raise PactContractError("Pact 文档超过结构复杂度上限")
    if isinstance(value, dict):
        for item in value.values():
            _validate_tree(item, depth=depth + 1, nodes=counter)
    elif isinstance(value, list):
        for item in value:
            _validate_tree(item, depth=depth + 1, nodes=counter)


def _json_matches(expected: JsonValue, actual: JsonValue) -> bool:
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and expected.keys() == actual.keys()
            and all(_json_matches(value, actual[key]) for key, value in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(expected) == len(actual)
            and all(
                _json_matches(left, right) for left, right in zip(expected, actual, strict=True)
            )
        )
    return type(expected) is type(actual) and expected == actual
