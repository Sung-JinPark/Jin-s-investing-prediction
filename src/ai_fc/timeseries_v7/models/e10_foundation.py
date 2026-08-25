"""Frozen foundation challenger receipt and zero-default-weight policy."""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class FoundationReceipt:
    checkpoint_sha256:str
    license_receipt_sha256:str
    fold_hash:str
    nested_oos_pass:bool=False
    calibration_pass:bool=False

    @property
    def weight(self)->float:
        return 1.0 if self.nested_oos_pass and self.calibration_pass else 0.0
