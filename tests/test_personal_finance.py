import pytest
from governor.personal_finance import PersonalFinance,Event,minor

def app():
    f=PersonalFinance()
    f.add_pot("Holiday",minor(3000),minor(200));f.add_pot("Car",minor(2000),minor(150));f.add_pot("Food",None,minor(300))
    f.map_category("Groceries","Food");return f

def test_category_totals_and_duplicate_protection():
    f=app();f.post(Event("allocation",minor(500),"2026-11-01",pot="Food"))
    r=f.submit_category_totals("2026-11",{"Groceries":"123.45","Unknown":"10"},"2026-11-30")
    assert r["needs_review"]==["Unknown"];assert f.balances()["Food"]==minor("376.55")
    with pytest.raises(ValueError):f.submit_category_totals("2026-11",{"Groceries":"123.45"},"2026-11-30")

def test_loan_is_zero_sum_and_repayment():
    f=app();f.post(Event("allocation",minor(1000),"2026-01-01",pot="Holiday"));f.post(Event("allocation",minor(100),"2026-01-01",pot="Car"))
    before=sum(f.balances().values());f.post(Event("loan",minor(400),"2026-01-02",pot="Holiday",counterparty_pot="Car"))
    assert sum(f.balances().values())==before;assert f.debt("Car","Holiday")==minor(400)
    f.post(Event("repayment",minor(150),"2026-02-01",pot="Car",counterparty_pot="Holiday"))
    assert f.debt("Car","Holiday")==minor(250)
    with pytest.raises(ValueError):f.post(Event("repayment",minor(251),"2026-02-02",pot="Car",counterparty_pot="Holiday"))

def test_transfer_has_no_debt():
    f=app();f.post(Event("allocation",minor(100),"2026-01-01",pot="Holiday"));f.post(Event("transfer",minor(20),"2026-01-02",pot="Holiday",counterparty_pot="Car"))
    assert f.debt("Car","Holiday")==0;assert f.balances()["Holiday"]==minor(80)

def test_correction_reverses_without_history_delete():
    f=app();old=f.post(Event("allocation",minor(100),"2026-01-01",pot="Holiday"))
    f.post(Event("correction",0,"2026-01-02",reverses=old,note="wrong allocation"))
    assert f.balances()["Holiday"]==0
    assert f.db.execute("select count(*) from pf_events").fetchone()[0]==2

def test_dashboard_counts_receivable_once_for_goal():
    f=app();f.post(Event("allocation",minor(1000),"2026-01-01",pot="Holiday"));f.post(Event("loan",minor(400),"2026-01-02",pot="Holiday",counterparty_pot="Car"))
    h=next(x for x in f.dashboard()["pots"] if x["name"]=="Holiday")
    assert h["balance_minor"]==minor(600);assert h["owed_to_pot_minor"]==minor(400);assert round(h["progress"],4)==round(1000/3000,4)
