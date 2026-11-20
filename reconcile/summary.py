from dataclasses import dataclass

from reconcile.missing import ManifestLine


@dataclass(frozen=True)
class MeasurementSummary:
    count: int
    minimum: int | None
    maximum: int | None


def summarize_measurements(lines: tuple[ManifestLine, ...]) -> MeasurementSummary:
    values = [line.item.converted for line in lines if line.item is not None]
    return MeasurementSummary(len(values), min(values, default=None), max(values, default=None))
