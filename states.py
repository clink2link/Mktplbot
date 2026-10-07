"""Compatibility wrapper for the canonical states package.

Use `from states import ...` in application code.
"""
from states import (
    LanguageState,
    VipManualState,
    FreeCodeState,
    GetFileState,
    UploadState,
    BuyState,
    AdminState,
    PaymentState,
    WithdrawState,
)

__all__ = [
    "LanguageState",
    "VipManualState",
    "FreeCodeState",
    "GetFileState",
    "UploadState",
    "BuyState",
    "AdminState",
    "PaymentState",
    "WithdrawState",
]
