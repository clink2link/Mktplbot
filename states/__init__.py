"""Canonical FSM states for the Mektpl bot.

Important:
The project contains a legacy top-level ``states.py`` as well as this
``states`` package.  Python resolves ``from states import ...`` to this
package, so all shared states are exported here.
"""

from aiogram.fsm.state import State, StatesGroup


class LanguageState(StatesGroup):
    selecting = State()


class VipManualState(StatesGroup):
    waiting_reason = State()


class FreeCodeState(StatesGroup):
    waiting_share = State()


class GetFileState(StatesGroup):
    wait_code = State()


class UploadState(StatesGroup):
    wait_type = State()
    wait_price = State()


class BuyState(StatesGroup):
    wait_payment = State()
    wait_confirm = State()


class AdminState(StatesGroup):
    wait_broadcast = State()
    wait_user_action = State()


class PaymentState(StatesGroup):
    wait_invoice = State()
    wait_callback = State()


class WithdrawState(StatesGroup):
    # Legacy withdraw flow
    amount = State()
    account_name = State()
    account_number = State()
    bank_name = State()
    confirm = State()

    # Creator/upgrade withdraw flow
    select_method = State()
    input_account_number = State()
    input_account_name = State()
    select_account = State()
    input_amount = State()
    confirm_withdraw = State()
    instant_select_account = State()
    instant_confirm = State()
    input_instant_amount = State()
    edit_account_name = State()


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
