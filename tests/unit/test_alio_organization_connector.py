from __future__ import annotations

from pydantic import SecretStr

from jobtology_db.connectors.sources import build_connector
from jobtology_db.settings import Settings


def test_official_numeric_200_result_code_is_accepted() -> None:
    source = build_connector(
        "alio_organization",
        Settings(DATA_GO_KR_SERVICE_KEY=SecretStr("shared-key")),
    )
    request = source.initial_requests()[0]

    metadata = source.validate_response(
        request,
        (
            b'{"resultCode":200,"resultMsg":"success","totalCount":1,'
            b'"pageNo":1,"result":[{"instCd":"C001"}]}'
        ),
        "application/json",
    )

    assert metadata.total_count == 1
    assert metadata.page_number == 1
