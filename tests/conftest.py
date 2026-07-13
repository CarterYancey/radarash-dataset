import zipfile
from pathlib import Path

import pytest

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


@pytest.fixture
def tickers_zip(tmp_path: Path) -> Path:
    return make_export_zip(tmp_path / "TICKERS.zip", TICKERS_CSV)


@pytest.fixture
def events_zip(tmp_path: Path) -> Path:
    return make_export_zip(tmp_path / "EVENTS.zip", EVENTS_CSV)
