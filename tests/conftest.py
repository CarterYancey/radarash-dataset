import zipfile
from pathlib import Path

import pytest

from ingest.convert import csv_to_parquet
from ingest.tables import TABLES

TICKERS_CSV = """\
table,permaticker,ticker,name,isdelisted,category,siccode,lastupdated
SEP,199059,TRUE,TrueCar Inc,N,Domestic Common Stock,7370,2024-01-05
SF1,199059,TRUE,TrueCar Inc,N,Domestic Common Stock,7370,2024-01-05
SEP,110963,AAPL,Apple Inc,N,Domestic Common Stock,3571,2024-01-05
SEP,159563,ENRNQ,Enron Corp,Y,Domestic Common Stock,6221,2018-11-09
"""

EVENTS_CSV = """\
date,ticker,eventcodes
2020-01-15,AAPL,21
2020-02-10,ENRNQ,"13,21,52"
2020-03-01,TRUE,71
"""


def make_export_zip(dest: Path, csv_text: str, member: str = "export.csv") -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, csv_text)
    return dest


# A TICKERS-shaped fixture exercising the identity rules:
# - AAPL appears for both SEP and SF1 (SF1 row must be ignored) …
# - … and GOOGL primary class in, GOOG secondary class out, SPY/BABA out.
# - BAC: bank (SIC 6021) excluded; O: REIT (SIC 6798) kept.
# - XYZ: one ticker, two permatickers (reuse).
# - NOSIC: missing SIC kept + flagged; NOFP: no firstpricedate (uncountable).
# - FINTECH: 'Financial Services' sector but non-financial SIC, kept; alive
#   with no lastpricedate (active through today).
# - DUP: two SEP rows, the later-lastupdated one must win.
IDENTITY_TICKERS_CSV = """\
table,permaticker,ticker,name,exchange,category,sector,industry,famaindustry,siccode,scalemarketcap,isdelisted,firstpricedate,lastpricedate,lastupdated
SEP,110963,AAPL,Apple Inc,NASDAQ,Domestic Common Stock,Technology,Consumer Electronics,Business Equipment,3571,6 - Mega,N,1998-01-02,2026-07-10,2026-07-10
SF1,110963,AAPL,Apple Inc (SF1 row),NASDAQ,Domestic Common Stock,Technology,Consumer Electronics,Business Equipment,3571,6 - Mega,N,1998-01-02,2026-07-10,2026-07-11
SEP,200001,WCOEQ,WorldCom Inc,OTC,Domestic Common Stock,Communication Services,Telecom Services,Communication,4813,5 - Large,Y,1998-01-02,2002-07-01,2018-11-09
SEP,200002,BAC,Bank of America,NYSE,Domestic Common Stock,Financial Services,Banks,Banking,6021,6 - Mega,N,1998-01-02,2026-07-10,2026-07-10
SEP,200003,O,Realty Income,NYSE,Domestic Common Stock,Real Estate,REIT - Retail,Trading,6798,5 - Large,N,1994-10-18,2026-07-10,2026-07-10
SEP,200004,SPY,SPDR S&P 500,NYSEARCA,ETF,,,,,,N,1993-01-29,2026-07-10,2026-07-10
SEP,200005,BABA,Alibaba ADR,NYSE,ADR Common Stock,Consumer Cyclical,Internet Retail,Retail,7389,6 - Mega,N,2014-09-19,2026-07-10,2026-07-10
SEP,200006,GOOGL,Alphabet A,NASDAQ,Domestic Common Stock Primary Class,Communication Services,Internet Content,Business Services,7370,6 - Mega,N,2004-08-19,2026-07-10,2026-07-10
SEP,200007,GOOG,Alphabet C,NASDAQ,Domestic Common Stock Secondary Class,Communication Services,Internet Content,Business Services,7370,6 - Mega,N,2014-03-27,2026-07-10,2026-07-10
SEP,200100,XYZ,XYZ Corp (old),NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3500,3 - Small,Y,1999-03-01,2001-06-30,2018-11-09
SEP,200101,XYZ,XYZ Holdings (new),NASDAQ,Domestic Common Stock,Industrials,Machinery,Machinery,3510,4 - Mid,N,2005-01-03,2026-07-10,2026-07-10
SEP,200102,NOSIC,No SIC Corp,OTC,Domestic Common Stock,Healthcare,Biotechnology,Pharmaceuticals,,2 - Micro,Y,2010-01-04,2015-12-31,2018-11-09
SEP,200103,NOFP,No FirstPrice Corp,OTC,Domestic Common Stock,Industrials,Machinery,Machinery,3520,2 - Micro,Y,,,2018-11-09
SEP,200104,FINTECH,Fintech Softworks,NASDAQ,Domestic Common Stock,Financial Services,Software - Infrastructure,Business Services,7372,4 - Mid,N,2015-06-01,,2026-07-10
SEP,200105,DUP,Dup Industries v1,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,2000,4 - Mid,N,2020-01-02,2026-07-10,2024-01-01
SEP,200105,DUP,Dup Industries v2,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,2000,4 - Mid,N,2020-01-02,2026-07-10,2025-01-01
"""


@pytest.fixture
def identity_tickers_parquet(tmp_path: Path) -> Path:
    """A TICKERS.parquet fixture built through the real ingest converter."""
    csv_path = tmp_path / "TICKERS_fixture.csv"
    csv_path.write_text(IDENTITY_TICKERS_CSV)
    out = tmp_path / "raw" / "TICKERS.parquet"
    csv_to_parquet(csv_path, TABLES["TICKERS"], out)
    return out


@pytest.fixture
def tickers_zip(tmp_path: Path) -> Path:
    return make_export_zip(tmp_path / "TICKERS.zip", TICKERS_CSV)


@pytest.fixture
def events_zip(tmp_path: Path) -> Path:
    return make_export_zip(tmp_path / "EVENTS.zip", EVENTS_CSV)
