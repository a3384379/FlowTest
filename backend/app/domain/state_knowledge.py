"""Deterministically derive bounded Context Knowledge from structured evidence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256

from app.domain.evidence_adapters import MappingEvidenceInput
from app.domain.test_contexts import (
    ContextKnowledgeEdge,
    ContextKnowledgeFact,
    ContextKnowledgeNode,
    ContextKnowledgeSnapshot,
    DatabaseExternalEvidenceStructuredData,
    ExternalDatabaseColumnClaim,
    ExternalDatabaseTableClaim,
    ExternalJavaBeanValidationClaim,
    ExternalJavaCallClaim,
    ExternalJavaControllerRouteClaim,
    ExternalJavaDtoFieldClaim,
    ExternalJavaEntityClaim,
    ExternalJavaEnumStateClaim,
    ExternalJavaExceptionClaim,
    ExternalJavaKafkaEventClaim,
    ExternalJavaPersistenceClaim,
    ExternalJavaTableColumnClaim,
    JavaExternalEvidenceStructuredData,
    evidence_state_scalar_text,
)

_DERIVED_ORIGIN = "flowtest.state_knowledge"
_MAX_NODES = 500
_MAX_EDGES = 1000
_MAX_FACTS = 50


class StateKnowledgeBudgetExceeded(ValueError):
    """Raised when evidence cannot fit in the bounded Context Knowledge graph."""


@dataclass(slots=True)
class _DerivedNode:
    id: str
    kind: str
    label: str
    facts: dict[str, str]


class _GraphBuilder:
    def __init__(self, current: ContextKnowledgeSnapshot) -> None:
        derived_ids = {
            node.id
            for node in current.nodes
            if node.id.startswith("generated.")
            and any(fact.name == "origin" and fact.value == _DERIVED_ORIGIN for fact in node.facts)
        }
        self._preserved_nodes = [node for node in current.nodes if node.id not in derived_ids]
        self._preserved_edges = [
            edge
            for edge in current.edges
            if edge.source not in derived_ids and edge.target not in derived_ids
        ]
        self._preserved_ids = {node.id for node in self._preserved_nodes}
        self._nodes: dict[str, _DerivedNode] = {}
        self._edges: set[tuple[str, str, str]] = set()

    def node(
        self,
        *,
        kind: str,
        identity: str,
        label: str,
        reference: str,
        evidence_ref: str,
        facts: dict[str, str] | None = None,
    ) -> str:
        node_id = _node_id(kind, identity)
        if node_id in self._preserved_ids:
            raise StateKnowledgeBudgetExceeded("derived knowledge node collides with initial graph")
        values = {
            "origin": _DERIVED_ORIGIN,
            "reference": reference,
            "evidence_ref": evidence_ref,
            **(facts or {}),
        }
        existing = self._nodes.get(node_id)
        if existing is None:
            self._nodes[node_id] = _DerivedNode(
                id=node_id,
                kind=kind,
                label=_bounded(label, 240),
                facts=values,
            )
            return node_id
        if existing.kind != kind:
            raise StateKnowledgeBudgetExceeded("derived knowledge node identity is ambiguous")
        bounded_label = _bounded(label, 240)
        if existing.label != bounded_label:
            existing.label = min(existing.label, bounded_label)
            existing.facts["requires_review"] = "true"
        for name, value in values.items():
            current = existing.facts.get(name)
            if current is None:
                existing.facts[name] = value
            elif current != value:
                existing.facts[name] = min(current, value)
                if name != "evidence_ref":
                    existing.facts["requires_review"] = "true"
        return node_id

    def edge(self, source: str, target: str, relation: str) -> None:
        if source != target:
            self._edges.add((source, target, relation))

    def reference(self, node_id: str) -> str:
        node = self._nodes.get(node_id)
        return "" if node is None else node.facts.get("reference", node.label)

    def snapshot(self) -> ContextKnowledgeSnapshot:
        derived_nodes = [
            ContextKnowledgeNode(
                id=node.id,
                kind=node.kind,
                label=node.label,
                facts=[
                    ContextKnowledgeFact(name=name, value=_bounded(value, 1000))
                    for name, value in sorted(node.facts.items())
                ],
            )
            for node in sorted(self._nodes.values(), key=lambda item: item.id)
        ]
        if any(len(node.facts) > _MAX_FACTS for node in derived_nodes):
            raise StateKnowledgeBudgetExceeded("derived knowledge node fact budget exceeded")
        edges = [
            *self._preserved_edges,
            *(
                ContextKnowledgeEdge(source=source, target=target, relation=relation)
                for source, target, relation in sorted(self._edges)
            ),
        ]
        nodes = [*self._preserved_nodes, *derived_nodes]
        if len(nodes) > _MAX_NODES or len(edges) > _MAX_EDGES:
            raise StateKnowledgeBudgetExceeded("derived knowledge graph budget exceeded")
        return ContextKnowledgeSnapshot(nodes=nodes, edges=edges)


def derive_state_knowledge(
    current: ContextKnowledgeSnapshot,
    evidence: list[MappingEvidenceInput],
) -> ContextKnowledgeSnapshot:
    """Rebuild the generated graph while preserving user-supplied Context Knowledge."""

    builder = _GraphBuilder(current)
    java_claims: list[tuple[str, object]] = []
    database_claims: list[tuple[str, object]] = []
    for item in sorted(evidence, key=lambda value: value.evidence_ref):
        structured = item.finding.structured_data
        if isinstance(structured, JavaExternalEvidenceStructuredData):
            java_claims.append((item.evidence_ref, structured.claim))
        elif isinstance(structured, DatabaseExternalEvidenceStructuredData):
            database_claims.append((item.evidence_ref, structured.claim))

    routes = _route_nodes(builder, java_claims)
    request_dtos, response_dtos, field_nodes = _dto_nodes(builder, java_claims, routes)
    services, entry_services = _call_nodes(builder, java_claims, routes)
    repositories = _repository_nodes(builder, java_claims, routes, services)
    entities = _entity_nodes(builder, java_claims)
    _table_column_nodes(builder, java_claims, entities)
    _database_nodes(builder, database_claims)
    _link_dtos_to_services(builder, request_dtos, response_dtos, entry_services)
    _link_repositories(builder, services, repositories, entities)
    _validation_nodes(builder, java_claims, field_nodes)
    _state_nodes(builder, java_claims, database_claims, routes, field_nodes)
    _outcome_nodes(builder, java_claims, routes)
    return builder.snapshot()


def _route_nodes(
    builder: _GraphBuilder,
    claims: list[tuple[str, object]],
) -> dict[str, tuple[str, set[str]]]:
    routes: dict[str, tuple[str, set[str]]] = {}
    for evidence_ref, claim in claims:
        if not isinstance(claim, ExternalJavaControllerRouteClaim):
            continue
        node_id = builder.node(
            kind="operation",
            identity=claim.operation_ref,
            label=f"{claim.method} {claim.path}",
            reference=claim.operation_ref,
            evidence_ref=evidence_ref,
            facts={
                "controller_ref": claim.controller_ref,
                "handler": claim.handler,
                "method": claim.method,
                "path": claim.path,
            },
        )
        route = routes.setdefault(claim.operation_ref, (node_id, set()))
        route[1].add(claim.controller_ref)
    return routes


def _dto_nodes(
    builder: _GraphBuilder,
    claims: list[tuple[str, object]],
    routes: dict[str, tuple[str, set[str]]],
) -> tuple[
    dict[str, set[str]],
    dict[str, set[str]],
    dict[tuple[str | None, str, str], set[str]],
]:
    request_dtos: dict[str, set[str]] = defaultdict(set)
    response_dtos: dict[str, set[str]] = defaultdict(set)
    field_nodes: dict[tuple[str | None, str, str], set[str]] = defaultdict(set)
    for evidence_ref, claim in claims:
        if not isinstance(claim, ExternalJavaDtoFieldClaim):
            continue
        dto_identity = f"{claim.operation_ref}|{claim.direction}|{claim.dto_type}"
        dto_id = builder.node(
            kind="dto",
            identity=dto_identity,
            label=claim.dto_type,
            reference=f"java://{claim.dto_type}",
            evidence_ref=evidence_ref,
            facts={"direction": claim.direction, "operation_ref": claim.operation_ref},
        )
        field_identity = f"{dto_identity}|{claim.field_name}"
        field_id = builder.node(
            kind="dto_field",
            identity=field_identity,
            label=f"{claim.dto_type}.{claim.field_name}",
            reference=f"field://{claim.dto_type}/{claim.field_name}",
            evidence_ref=evidence_ref,
            facts={"field_type": claim.field_type, "direction": claim.direction},
        )
        builder.edge(dto_id, field_id, "contains")
        route = routes.get(claim.operation_ref)
        if route is not None:
            builder.edge(
                route[0],
                dto_id,
                "accepts" if claim.direction == "request" else "returns",
            )
        target = request_dtos if claim.direction == "request" else response_dtos
        target[claim.operation_ref].add(dto_id)
        field_nodes[(claim.operation_ref, claim.dto_type, claim.field_name)].add(field_id)
    return request_dtos, response_dtos, field_nodes


def _call_nodes(
    builder: _GraphBuilder,
    claims: list[tuple[str, object]],
    routes: dict[str, tuple[str, set[str]]],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    services: dict[str, set[str]] = defaultdict(set)
    entry_services: dict[str, set[str]] = defaultdict(set)
    for evidence_ref, claim in claims:
        if not isinstance(claim, ExternalJavaCallClaim):
            continue
        route = routes.get(claim.operation_ref)
        callee_kind = "client" if claim.kind == "feign_call" else "service"
        callee_ref = (
            claim.callee_ref
            if claim.kind == "feign_call"
            else _java_component_ref(claim.callee_ref)
        )
        callee = builder.node(
            kind=callee_kind,
            identity=callee_ref,
            label=_reference_label(callee_ref),
            reference=callee_ref,
            evidence_ref=evidence_ref,
        )
        if route is None:
            continue
        if _controller_caller(claim.caller_ref, route[1]):
            source = route[0]
            if claim.kind == "service_call":
                entry_services[claim.operation_ref].add(callee)
        else:
            caller_ref = _java_component_ref(claim.caller_ref)
            source = builder.node(
                kind="service",
                identity=caller_ref,
                label=_reference_label(caller_ref),
                reference=caller_ref,
                evidence_ref=evidence_ref,
            )
            builder.edge(route[0], source, "enters")
            services[claim.operation_ref].add(source)
        builder.edge(source, callee, "invokes" if claim.kind == "feign_call" else "calls")
        if claim.kind == "service_call":
            services[claim.operation_ref].add(callee)
    return services, entry_services


def _repository_nodes(
    builder: _GraphBuilder,
    claims: list[tuple[str, object]],
    routes: dict[str, tuple[str, set[str]]],
    services: dict[str, set[str]],
) -> list[tuple[str, str, str | None, str | None]]:
    repositories: list[tuple[str, str, str | None, str | None]] = []
    for evidence_ref, claim in claims:
        if not isinstance(claim, ExternalJavaPersistenceClaim):
            continue
        repository = builder.node(
            kind="repository",
            identity=claim.repository_ref,
            label=_reference_label(claim.repository_ref),
            reference=claim.repository_ref,
            evidence_ref=evidence_ref,
        )
        repositories.append(
            (
                claim.repository_ref,
                repository,
                claim.operation_ref,
                claim.entity_ref,
            )
        )
        if claim.operation_ref is None:
            continue
        matched_services = sorted(
            {
                service
                for service in services.get(claim.operation_ref, set())
                if _node_token(service, builder) == _domain_token(claim.repository_ref)
            }
        )
        if len(matched_services) == 1:
            builder.edge(matched_services[0], repository, "uses_repository")
        elif claim.operation_ref in routes:
            builder.edge(routes[claim.operation_ref][0], repository, "uses_repository")
    return repositories


def _entity_nodes(
    builder: _GraphBuilder,
    claims: list[tuple[str, object]],
) -> dict[str, tuple[str, str]]:
    entities: dict[str, tuple[str, str]] = {}
    for evidence_ref, claim in claims:
        if not isinstance(claim, ExternalJavaEntityClaim):
            continue
        entity = builder.node(
            kind="entity",
            identity=claim.entity_ref,
            label=claim.class_name,
            reference=claim.entity_ref,
            evidence_ref=evidence_ref,
            facts={"class_name": claim.class_name},
        )
        entities[claim.entity_ref] = (entity, claim.class_name)
        if claim.table_ref is not None:
            table = _table_node(builder, claim.table_ref, evidence_ref)
            builder.edge(entity, table, "maps_to")
    return entities


def _table_column_nodes(
    builder: _GraphBuilder,
    claims: list[tuple[str, object]],
    entities: dict[str, tuple[str, str]],
) -> None:
    for evidence_ref, claim in claims:
        if not isinstance(claim, ExternalJavaTableColumnClaim):
            continue
        entity_entry = entities.get(claim.entity_ref)
        entity = (
            entity_entry[0]
            if entity_entry is not None
            else builder.node(
                kind="entity",
                identity=claim.entity_ref,
                label=_reference_label(claim.entity_ref),
                reference=claim.entity_ref,
                evidence_ref=evidence_ref,
            )
        )
        table = _table_node(builder, claim.table_ref, evidence_ref)
        column = builder.node(
            kind="table_column",
            identity=f"{_canonical_table_ref(claim.table_ref)}|{claim.column_name}",
            label=f"{_table_label(claim.table_ref)}.{claim.column_name}",
            reference=f"column://{_canonical_table_ref(claim.table_ref)}/{claim.column_name}",
            evidence_ref=evidence_ref,
            facts={"field_name": claim.field_name, "column_name": claim.column_name},
        )
        builder.edge(entity, table, "maps_to")
        builder.edge(entity, column, "has_field")
        builder.edge(table, column, "has_column")


def _database_nodes(builder: _GraphBuilder, claims: list[tuple[str, object]]) -> None:
    for evidence_ref, claim in claims:
        if isinstance(claim, ExternalDatabaseTableClaim):
            _table_node(builder, f"table://{claim.schema_name}/{claim.name}", evidence_ref)
        elif isinstance(claim, ExternalDatabaseColumnClaim):
            table_ref = f"table://{claim.schema_name}/{claim.table_name}"
            table = _table_node(builder, table_ref, evidence_ref)
            column = _database_column_node(builder, claim, evidence_ref)
            builder.edge(table, column, "has_column")


def _link_dtos_to_services(
    builder: _GraphBuilder,
    request_dtos: dict[str, set[str]],
    response_dtos: dict[str, set[str]],
    entry_services: dict[str, set[str]],
) -> None:
    for operation_ref, services in entry_services.items():
        for dto in request_dtos.get(operation_ref, set()):
            for service in services:
                builder.edge(dto, service, "handled_by")
        for service in services:
            for dto in response_dtos.get(operation_ref, set()):
                builder.edge(service, dto, "produces")


def _link_repositories(
    builder: _GraphBuilder,
    services: dict[str, set[str]],
    repositories: list[tuple[str, str, str | None, str | None]],
    entities: dict[str, tuple[str, str]],
) -> None:
    all_services = {node for values in services.values() for node in values}
    services_by_token = _nodes_by_token(all_services, builder)
    repository_nodes_by_token: dict[str, set[str]] = defaultdict(set)
    entity_nodes_by_token: dict[str, set[str]] = defaultdict(set)
    for repository_ref, repository, _operation_ref, _entity_ref in repositories:
        repository_nodes_by_token[_domain_token(repository_ref)].add(repository)
    for entity, class_name in entities.values():
        entity_nodes_by_token[_domain_token(class_name)].add(entity)
    for repository_ref, repository, operation_ref, entity_ref in repositories:
        repository_token = _domain_token(repository_ref)
        if (
            repository_token
            and operation_ref is None
            and len(repository_nodes_by_token[repository_token]) == 1
            and len(services_by_token[repository_token]) == 1
        ):
            service = next(iter(services_by_token[repository_token]))
            builder.edge(service, repository, "may_use_repository")
        if entity_ref is not None and entity_ref in entities:
            builder.edge(repository, entities[entity_ref][0], "maps_entity")
            continue
        if (
            repository_token
            and len(repository_nodes_by_token[repository_token]) == 1
            and len(entity_nodes_by_token[repository_token]) == 1
        ):
            entity = next(iter(entity_nodes_by_token[repository_token]))
            builder.edge(repository, entity, "may_map_entity")


def _validation_nodes(
    builder: _GraphBuilder,
    claims: list[tuple[str, object]],
    field_nodes: dict[tuple[str | None, str, str], set[str]],
) -> None:
    for evidence_ref, claim in claims:
        if not isinstance(claim, ExternalJavaBeanValidationClaim):
            continue
        identity = (
            f"{claim.operation_ref}|{claim.dto_type}|{claim.field_name}|"
            f"{claim.annotation}|{claim.constraint}"
        )
        constraint = builder.node(
            kind="validation",
            identity=identity,
            label=f"{claim.annotation} {claim.constraint}",
            reference=f"validation://{claim.dto_type}/{claim.field_name}/{claim.annotation}",
            evidence_ref=evidence_ref,
            facts={"constraint": claim.constraint},
        )
        for field in field_nodes.get(
            (claim.operation_ref, claim.dto_type, claim.field_name), set()
        ):
            builder.edge(field, constraint, "constrained_by")


def _state_nodes(
    builder: _GraphBuilder,
    java_claims: list[tuple[str, object]],
    database_claims: list[tuple[str, object]],
    routes: dict[str, tuple[str, set[str]]],
    field_nodes: dict[tuple[str | None, str, str], set[str]],
) -> None:
    for evidence_ref, claim in java_claims:
        if not isinstance(claim, ExternalJavaEnumStateClaim):
            continue
        state = builder.node(
            kind="state_candidate",
            identity=f"{claim.operation_ref}|{claim.enum_ref}",
            label=_reference_label(claim.enum_ref),
            reference=claim.enum_ref,
            evidence_ref=evidence_ref,
            facts=_state_facts(claim.values),
        )
        matched_fields = (
            field_nodes.get((claim.operation_ref, claim.dto_type, claim.field_name), set())
            if claim.dto_type is not None and claim.field_name is not None
            else set()
        )
        if matched_fields:
            for field in matched_fields:
                builder.edge(field, state, "allows_state")
        elif claim.operation_ref is not None and claim.operation_ref in routes:
            builder.edge(routes[claim.operation_ref][0], state, "allows_state")
    for evidence_ref, claim in database_claims:
        if not isinstance(claim, ExternalDatabaseColumnClaim):
            continue
        values = [
            *claim.enum_values,
            *(
                claim.observed_distribution.enum_candidates
                if claim.observed_distribution is not None
                else []
            ),
        ]
        if not values:
            continue
        table_ref = f"table://{claim.schema_name}/{claim.table_name}"
        column = _database_column_node(builder, claim, evidence_ref)
        state = builder.node(
            kind="state_candidate",
            identity=f"{_canonical_table_ref(table_ref)}|{claim.name}|database",
            label=f"{claim.table_name}.{claim.name} state",
            reference=f"state-set://{claim.schema_name}/{claim.table_name}/{claim.name}",
            evidence_ref=evidence_ref,
            facts=_state_facts([evidence_state_scalar_text(value) for value in values]),
        )
        builder.edge(column, state, "allows_state")


def _outcome_nodes(
    builder: _GraphBuilder,
    claims: list[tuple[str, object]],
    routes: dict[str, tuple[str, set[str]]],
) -> None:
    for evidence_ref, claim in claims:
        if isinstance(claim, ExternalJavaExceptionClaim):
            node = builder.node(
                kind="exception",
                identity=f"{claim.operation_ref}|{claim.exception_type}|{claim.outcome}",
                label=claim.exception_type,
                reference=f"java://{claim.exception_type}",
                evidence_ref=evidence_ref,
                facts={"outcome": claim.outcome},
            )
            relation = "may_raise"
        elif isinstance(claim, ExternalJavaKafkaEventClaim):
            node = builder.node(
                kind="event",
                identity=f"{claim.direction}|{claim.topic_ref}|{claim.event_type}",
                label=claim.event_type,
                reference=claim.topic_ref,
                evidence_ref=evidence_ref,
                facts={"direction": claim.direction, "event_type": claim.event_type},
            )
            relation = "produces" if claim.direction == "produce" else "consumes"
        else:
            continue
        if claim.operation_ref is not None and claim.operation_ref in routes:
            builder.edge(routes[claim.operation_ref][0], node, relation)


def _database_column_node(
    builder: _GraphBuilder,
    claim: ExternalDatabaseColumnClaim,
    evidence_ref: str,
) -> str:
    table_ref = f"table://{claim.schema_name}/{claim.table_name}"
    return builder.node(
        kind="table_column",
        identity=f"{_canonical_table_ref(table_ref)}|{claim.name}",
        label=f"{claim.table_name}.{claim.name}",
        reference=f"column://{claim.schema_name}/{claim.table_name}/{claim.name}",
        evidence_ref=evidence_ref,
        facts={
            "data_type": claim.data_type,
            "nullable": str(claim.nullable).lower(),
        },
    )


def _table_node(builder: _GraphBuilder, table_ref: str, evidence_ref: str) -> str:
    canonical = _canonical_table_ref(table_ref)
    return builder.node(
        kind="table",
        identity=canonical,
        label=canonical,
        reference=f"table://{canonical}",
        evidence_ref=evidence_ref,
    )


def _state_facts(values: Sequence[object]) -> dict[str, str]:
    normalized = sorted({str(value) for value in values})
    sample = ", ".join(normalized[:10])
    return {
        "value_count": str(len(normalized)),
        "value_sample": _bounded(sample, 900) if sample else "none",
    }


def _controller_caller(caller_ref: str, controller_refs: set[str]) -> bool:
    return any(
        caller_ref == controller_ref or caller_ref.startswith(f"{controller_ref}.")
        for controller_ref in controller_refs
    )


def _node_token(node_id: str, builder: _GraphBuilder) -> str:
    return _domain_token(builder.reference(node_id))


def _nodes_by_token(nodes: set[str], builder: _GraphBuilder) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = defaultdict(set)
    for node in nodes:
        grouped[_node_token(node, builder)].add(node)
    return grouped


def _java_component_ref(reference: str) -> str:
    scheme, separator, value = reference.partition("://")
    if not separator or "." not in value:
        return reference
    component, _method = value.rsplit(".", 1)
    return f"{scheme}://{component}"


def _domain_token(reference: str) -> str:
    value = _reference_label(reference).split("/", 1)[0].rsplit(".", 1)[-1]
    if len(value) > 1 and value[0] == "I" and value[1].isupper():
        value = value[1:]
    for suffix in (
        "RepositoryImpl",
        "ServiceImpl",
        "Repository",
        "Service",
        "Mapper",
        "Client",
        "Dao",
    ):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    return "".join(character.lower() for character in value if character.isalnum())


def _reference_label(reference: str) -> str:
    return _bounded(reference.split("://", 1)[-1], 240)


def _canonical_table_ref(table_ref: str) -> str:
    value = table_ref.removeprefix("table://").strip("/")
    if "/" not in value and value.count(".") == 1:
        value = value.replace(".", "/")
    return value


def _table_label(table_ref: str) -> str:
    return _canonical_table_ref(table_ref).replace("/", ".")


def _node_id(kind: str, identity: str) -> str:
    digest = sha256(f"{kind}\0{identity}".encode()).hexdigest()[:24]
    return f"generated.{kind}:{digest}"


def _bounded(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"
