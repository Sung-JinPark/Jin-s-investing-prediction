"""NASDAQ multivariate time-series V8 research namespace.

V8 studies a calibrated distribution layer (volatility term structure,
bounded location anchor, baseline blend, PIT recalibration) on top of the
frozen V2 ridge-VARX engine.  It reads the V2 PIT ledgers and DFM caches
read-only and writes exclusively under the V8 namespace.  With neutral
parameters V8 must reproduce the V2 distribution exactly.
"""

from .contracts import MODEL_ID, MODEL_VERSION, load_contract_v8

__all__ = ["MODEL_ID", "MODEL_VERSION", "load_contract_v8"]
