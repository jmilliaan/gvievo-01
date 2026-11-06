"""Every built message against the VDA5050 JSON schemas. Skipped unless VDA5050_SCHEMAS names their
directory (the station repo's VDA5050/json_schemas). This checks the schema only: the system is a subset,
and not compliant (contract section 10)."""

import json
import os
import pathlib

import contract
import pytest
from test_vda_state import SITE, VIEWS

from amr_station import vda_order as vo
from amr_station import vda_state as vs

jsonschema = pytest.importorskip("jsonschema")
SCHEMAS = os.environ.get("VDA5050_SCHEMAS")
if not SCHEMAS:
    pytest.skip("set VDA5050_SCHEMAS to the VDA5050 json_schemas directory", allow_module_level=True)

HEADER = {
    "headerId": 1,
    "timestamp": "2026-11-05T01:15:31.200Z",
    "version": "3.0.0",
    "manufacturer": "gvi",
    "serialNumber": "agv1",
}


def schema(name):
    return json.loads((pathlib.Path(SCHEMAS) / f"{name}.schema").read_text())


@pytest.mark.parametrize("title", list(VIEWS))
def test_every_state_validates(title):
    jsonschema.validate({**HEADER, **vs.build_state(VIEWS[title], SITE)}, schema("state"))


@pytest.mark.parametrize("state", ["ONLINE", "OFFLINE", "CONNECTION_BROKEN"])
def test_every_connection_validates(state):
    jsonschema.validate({**HEADER, "connectionState": state}, schema("connection"))


def test_the_order_and_the_cancel_validate():
    doc = {
        **HEADER,
        "orderId": "O",
        "orderUpdateId": 0,
        "seenStateHeaderId": 1,
        **vo.canonical_order(SITE, "MRU3", "O"),
    }
    jsonschema.validate(doc, schema("order"))
    jsonschema.validate(contract.contract_cancel(), schema("instantActions"))
