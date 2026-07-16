import pytest
from app.reference import compare_ordinal, parse_measurement, canonical_vein


def test_ceap_ordering():
    assert compare_ordinal("C3", "C2") > 0
    assert compare_ordinal("C2", "C2") == 0
    assert compare_ordinal("C1", "C2") < 0
    assert compare_ordinal("C2r", "C2") > 0  # recurrent ranks above C2


def test_ceap_unknown_raises():
    with pytest.raises(ValueError):
        compare_ordinal("C9", "C2")


def test_parse_measurement_takes_lower_bound():
    assert parse_measurement("3 mm") == 3.0
    assert parse_measurement("3-4 mm") == 3.0     # conservative
    assert parse_measurement("3.5") == 3.5
    assert parse_measurement("no measurement") is None


def test_parse_measurement_rejects_booleans():
    assert parse_measurement(True) is None
    assert parse_measurement(False) is None


def test_vein_synonyms():
    assert canonical_vein("GSV") == "great_saphenous"
    assert canonical_vein("great saphenous vein") == "great_saphenous"
    assert canonical_vein("long saphenous") == "great_saphenous"
    assert canonical_vein("unknown vein") is None
