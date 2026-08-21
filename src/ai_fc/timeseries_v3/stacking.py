"""No-regret distribution stacking with a fixed anchor floor."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .interfaces import ComponentForecast


def validate_weights(weights: dict[str, float], *, anchor: str, anchor_floor: float) -> None:
    if anchor not in weights or weights[anchor] + 1e-12 < anchor_floor:
        raise ValueError("anchor floor violated")
    if any(value < -1e-12 for value in weights.values()):
        raise ValueError("component weight is negative")
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        raise ValueError("component weights must sum to one")


def constrained_loss_weights(
    mean_component_losses: dict[str, float], *, anchor: str, anchor_floor: float,
    previous: dict[str, float] | None = None, stability_penalty: float = 0.02,
    complexity_penalty: float = 0.005, unavailable: set[str] | None = None,
) -> dict[str, float]:
    unavailable = unavailable or set()
    eligible = {key: float(value) for key, value in mean_component_losses.items() if key not in unavailable}
    if anchor not in eligible:
        raise ValueError("fixed anchor is unavailable")
    anchor_loss = eligible[anchor]
    # A challenger with no ex-ante loss advantage receives exactly zero.  This is
    # the operational no-regret guard; it is not a row-wise oracle because only
    # the trailing resolved window is used for the next origin.
    improving = {
        key: loss for key, loss in eligible.items()
        if key == anchor or loss < anchor_loss
    }
    if len(improving) == 1:
        return {key: (1.0 if key == anchor else 0.0) for key in mean_component_losses}
    advantages = np.array([anchor_loss - loss for key, loss in improving.items() if key != anchor])
    scale = max(float(np.median(np.abs(advantages))), anchor_loss * 0.0025, 1e-8)
    raw: dict[str, float] = {}
    for key, loss in improving.items():
        prior = 0.0 if previous is None else float(previous.get(key, 0.0))
        score = 1.0 if key == anchor else np.exp((anchor_loss - loss) / scale)
        score *= np.exp(-complexity_penalty)
        score += stability_penalty * prior
        raw[key] = float(score)
    total = sum(raw.values())
    weights = {key: value / total for key, value in raw.items()}
    if weights[anchor] < anchor_floor:
        remainder = 1.0 - anchor_floor
        other_total = sum(value for key, value in weights.items() if key != anchor)
        weights = {
            key: (anchor_floor if key == anchor else remainder * value / other_total)
            for key, value in weights.items()
        } if other_total else {anchor: 1.0}
    for key in mean_component_losses:
        weights.setdefault(key, 0.0)
    validate_weights(weights, anchor=anchor, anchor_floor=anchor_floor)
    return weights


def mix_samples(
    samples: dict[str, np.ndarray], weights: dict[str, float], *, count: int,
    rng: np.random.Generator,
) -> np.ndarray:
    labels = [key for key, weight in weights.items() if weight > 0 and key in samples]
    probabilities = np.array([weights[key] for key in labels], dtype=float)
    probabilities /= probabilities.sum()
    selected = rng.choice(len(labels), size=count, p=probabilities)
    output = np.empty(count)
    for index, label in enumerate(labels):
        mask = selected == index
        if mask.any():
            output[mask] = rng.choice(np.asarray(samples[label], dtype=float), int(mask.sum()), replace=True)
    return output


@dataclass(frozen=True)
class StackedDistribution:
    weights_by_horizon: dict[int, dict[str, float]]
    anchor_component: str
    anchor_floor: float

    def combine(
        self, forecasts: dict[str, ComponentForecast], *, count: int, seed: int,
        event_present: bool, stale_components: set[str] | None = None,
    ) -> dict[int, np.ndarray]:
        rng = np.random.default_rng(seed)
        stale_components = set(stale_components or set())
        if not event_present:
            stale_components.add("event")
        output: dict[int, np.ndarray] = {}
        for horizon, stored_weights in self.weights_by_horizon.items():
            active = {
                key: (0.0 if key in stale_components or key not in forecasts else value)
                for key, value in stored_weights.items()
            }
            if active.get(self.anchor_component, 0.0) <= 0:
                raise ValueError("anchor cannot be stale")
            total = sum(active.values())
            active = {key: value / total for key, value in active.items()}
            if active[self.anchor_component] < self.anchor_floor:
                other = sum(value for key, value in active.items() if key != self.anchor_component)
                remainder = 1.0 - self.anchor_floor
                active = {
                    key: self.anchor_floor if key == self.anchor_component else remainder * value / other
                    for key, value in active.items()
                } if other else {self.anchor_component: 1.0}
            validate_weights(active, anchor=self.anchor_component, anchor_floor=self.anchor_floor)
            output[horizon] = mix_samples(
                {key: forecast.horizon_samples[horizon] for key, forecast in forecasts.items()},
                active, count=count, rng=rng,
            )
        return output
