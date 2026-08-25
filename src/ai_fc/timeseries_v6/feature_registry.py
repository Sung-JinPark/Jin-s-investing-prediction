"""Frozen feature identities; duplicates and undocumented transforms fail closed."""

from dataclasses import dataclass


class FeatureRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class FeatureDefinition:
    feature_name: str
    source_ids: tuple[str, ...]
    transformation_id: str
    output_unit: str
    block: str


def validate_feature_registry(features: list[FeatureDefinition]) -> dict[str, FeatureDefinition]:
    if not features:
        raise FeatureRegistryError("feature registry must not be empty")
    result: dict[str, FeatureDefinition] = {}
    coordinates: set[tuple[tuple[str, ...], str, str]] = set()
    for feature in features:
        if feature.feature_name in result:
            raise FeatureRegistryError(f"duplicate feature name: {feature.feature_name}")
        coordinate = (tuple(sorted(feature.source_ids)), feature.transformation_id, feature.output_unit)
        if coordinate in coordinates:
            raise FeatureRegistryError(f"duplicate feature semantics: {feature.feature_name}")
        if not feature.source_ids or not feature.transformation_id or not feature.output_unit:
            raise FeatureRegistryError(f"incomplete feature definition: {feature.feature_name}")
        result[feature.feature_name] = feature
        coordinates.add(coordinate)
    return result
