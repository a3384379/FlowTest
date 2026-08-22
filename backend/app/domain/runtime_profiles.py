from dataclasses import dataclass
from enum import StrEnum


class RuntimeProfile(StrEnum):
    FULL = "full"
    COMPACT = "compact"
    STANDALONE = "standalone"


class WorkerTopology(StrEnum):
    ISOLATED = "isolated"
    CONSOLIDATED = "consolidated"
    IN_PROCESS = "in_process"


class RuntimeFeature(StrEnum):
    PERFORMANCE_LAB = "performance_lab"
    ENVIRONMENT_LAB = "environment_lab"


@dataclass(frozen=True, slots=True)
class RuntimeProfileDescription:
    profile: RuntimeProfile
    worker_topology: WorkerTopology
    unavailable_features: tuple[RuntimeFeature, ...]


def describe_runtime_profile(profile: RuntimeProfile) -> RuntimeProfileDescription:
    if profile is RuntimeProfile.COMPACT:
        return RuntimeProfileDescription(
            profile=profile,
            worker_topology=WorkerTopology.CONSOLIDATED,
            unavailable_features=(
                RuntimeFeature.PERFORMANCE_LAB,
                RuntimeFeature.ENVIRONMENT_LAB,
            ),
        )
    if profile is RuntimeProfile.STANDALONE:
        return RuntimeProfileDescription(
            profile=profile,
            worker_topology=WorkerTopology.IN_PROCESS,
            unavailable_features=(
                RuntimeFeature.PERFORMANCE_LAB,
                RuntimeFeature.ENVIRONMENT_LAB,
            ),
        )
    return RuntimeProfileDescription(
        profile=profile,
        worker_topology=WorkerTopology.ISOLATED,
        unavailable_features=(),
    )
