"""Redacted status report model."""

from __future__ import annotations


def status_report(*,loop_state:str,data_freshness:dict,drift:dict,budget:dict,gates:dict,numbers:dict|None,all_approved:bool)->dict:
    visible=all_approved and all(gates.get(name) is True for name in ('integrity','qualification','operational','prospective'))
    return {'loop_state':loop_state,'data_freshness':data_freshness,'drift':drift,'budget':budget,'gates':gates,'forecast_numbers':numbers if visible else None,'numbers_visible':visible,'automatic_publication':False,'automatic_trading':False}
