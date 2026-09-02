# tests/prices/sbs/valor_cuota/test_afps.py
# ---------------------------------------------------------------
# Pins down the AFP registry contract (config/afps.yaml):
#   - alias resolution folds accents, case and the 'AFP ' prefix,
#     so a corporate rename never orphans historical data
#   - procode naming is derived from the clave, never the name
#   - exactly one AFP declares itself the house
# No DB.
# ---------------------------------------------------------------

from src.pipelines.prices.sbs.valor_cuota import afps


def test_clave_resolves_name_alias_and_accents():
    assert afps.clave_de("HABITAT") == "habitat"
    assert afps.clave_de("AFP HÁBITAT") == "habitat"
    assert afps.clave_de("habitat") == "habitat"
    assert afps.clave_de("  afp  habitat ") == "habitat"


def test_unknown_afp_resolves_to_none():
    assert afps.clave_de("AFP INEXISTENTE") is None


def test_procode_is_clave_based():
    assert afps.procode("AFP PROFUTURO", 2) == "SPP_PROFUTURO_F2"
    assert afps.procode("profuturo", 0) == "SPP_PROFUTURO_F0"


def test_procode_roundtrips_through_parse():
    code = afps.procode("INTEGRA", 3)
    assert afps.parse_procode(code) == ("integra", 3)


def test_bench_procode_is_not_a_fund():
    assert afps.parse_procode(afps.procode_bench(1)) is None


def test_exactly_one_house_afp():
    casas = [a for a in afps.afps() if a.get("casa")]
    assert len(casas) == 1
    assert afps.afp_casa() == casas[0]["nombre"]


def test_metric_field_map_is_total():
    assert set(afps.METRICA_FIELD) == {"valor_cuota", "cuotas", "fondo"}
    assert set(afps.FIELD_METRICA) == {"PX_LAST", "CUOTAS", "FONDO_SOLES"}
