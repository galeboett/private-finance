from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Account, HoldingSnapshot, NetWorthSnapshot, OperationChange, StatementCheckpoint, Transaction
from app.services.importers_ofx import commit_ofx_import, parse_ofx


SGML_CHECKING = b"""OFXHEADER:100
DATA:OFXSGML
VERSION:102

<OFX>
<BANKMSGSRSV1><STMTTRNRS><STMTRS>
<BANKACCTFROM><BANKID>021000021<ACCTID>1234567890<ACCTTYPE>CHECKING
<BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260701120000<TRNAMT>-42.10<FITID>FIT-1001<NAME>GROCERY STORE<MEMO>WEEKLY SHOP
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260702120000<TRNAMT>1000.00<FITID>FIT-1002<NAME>PAYROLL
</BANKTRANLIST>
<LEDGERBAL><BALAMT>2450.33<DTASOF>20260702235959
</STMTRS></STMTTRNRS></BANKMSGSRSV1>
</OFX>"""


XML_CARD = b"""<?xml version="1.0" encoding="UTF-8"?>
<OFX><CREDITCARDMSGSRSV1><CCSTMTTRNRS><CCSTMTRS>
<CCACCTFROM><ACCTID>99990001</ACCTID></CCACCTFROM>
<BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20260710</DTPOSTED><TRNAMT>-12.34</TRNAMT><FITID>CARD-1</FITID><NAME>CAFE</NAME></STMTTRN>
</BANKTRANLIST>
<LEDGERBAL><BALAMT>-123.45</BALAMT><DTASOF>20260710</DTASOF></LEDGERBAL>
</CCSTMTRS></CCSTMTTRNRS></CREDITCARDMSGSRSV1></OFX>"""


XML_INVESTMENT = b"""<?xml version="1.0"?>
<OFX><INVSTMTMSGSRSV1><INVSTMTTRNRS><INVSTMTRS>
<INVACCTFROM><BROKERID>Fidelity</BROKERID><ACCTID>Z12345678</ACCTID></INVACCTFROM>
<INVPOSLIST><POSSTOCK><SECID><UNIQUEID>922908769</UNIQUEID><UNIQUEIDTYPE>CUSIP</UNIQUEIDTYPE></SECID><HELDINACCT>CASH</HELDINACCT><POSTYPE>LONG</POSTYPE><UNITS>2.5</UNITS><UNITPRICE>250.00</UNITPRICE><MKTVAL>625.00</MKTVAL><DTPRICEASOF>20260714120000</DTPRICEASOF></POSSTOCK></INVPOSLIST>
</INVSTMTRS></INVSTMTTRNRS></INVSTMTMSGSRSV1>
<SECLISTMSGSRSV1><SECLIST><STOCKINFO><SECINFO><SECID><UNIQUEID>922908769</UNIQUEID><UNIQUEIDTYPE>CUSIP</UNIQUEIDTYPE></SECID><SECNAME>Vanguard Total Stock</SECNAME><TICKER>VTI</TICKER></SECINFO></STOCKINFO></SECLIST></SECLISTMSGSRSV1>
</OFX>"""


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_parse_ofx_1x_sgml_transactions_and_ledger_balance():
    parsed = parse_ofx(SGML_CHECKING)

    assert parsed.account["last_four"] == "7890"
    assert parsed.account["account_type"] == "checking"
    assert [row["row_kind"] for row in parsed.rows] == ["transaction", "transaction", "balance_anchor"]
    assert parsed.rows[0]["source_reference"] == "FIT-1001"
    assert parsed.rows[0]["amount"] == "-42.10"
    assert parsed.rows[2]["statement_date"] == "2026-07-02"
    assert parsed.rows[2]["statement_balance"] == "2450.33"


def test_parse_ofx_2x_xml_credit_card():
    parsed = parse_ofx(XML_CARD)

    assert parsed.account["account_type"] == "credit_card"
    assert parsed.rows[0]["raw_description"] == "CAFE"
    assert parsed.rows[1]["statement_balance"] == "-123.45"


def test_commit_ofx_uses_fitid_dedupe_and_creates_anchor_in_one_operation():
    with _session() as session:
        account = Account(display_name="Checking 7890", account_type="checking", last_four="7890")
        session.add(account)
        session.commit()

        first = commit_ofx_import(session, account, "checking.qfx", SGML_CHECKING, actor="user:1")
        session.commit()
        second = commit_ofx_import(session, account, "checking-copy.qfx", SGML_CHECKING, actor="user:1")
        session.commit()

        assert first["inserted"] == 3
        assert second["inserted"] == 1  # the balance anchor is idempotently refreshed
        assert second["skipped"] == 2
        assert session.query(Transaction).count() == 2
        checkpoint = session.query(StatementCheckpoint).one()
        assert checkpoint.statement_date == date(2026, 7, 2)
        assert checkpoint.statement_balance_cents == 245033
        snapshot = session.query(NetWorthSnapshot).one()
        assert snapshot.balance_cents == 245033
        change_types = {
            row.entity_type
            for row in session.query(OperationChange).filter(OperationChange.operation_id == first["operation_id"])
        }
        assert change_types == {"transaction", "statement_checkpoint", "net_worth_snapshot"}


def test_commit_ofx_investment_positions_create_holding_snapshot_anchor():
    with _session() as session:
        account = Account(display_name="Fidelity Brokerage", account_type="brokerage", last_four="5678")
        session.add(account)
        session.commit()

        result = commit_ofx_import(session, account, "positions.ofx", XML_INVESTMENT, actor="user:1")
        session.commit()

        holding = session.query(HoldingSnapshot).one()
        assert result["inserted"] == 1
        assert holding.snapshot_date == date(2026, 7, 14)
        assert holding.symbol == "VTI"
        assert holding.quantity_basis_points == 25000
        assert holding.market_value_cents == 62500
        assert session.query(NetWorthSnapshot).one().balance_cents == 62500
