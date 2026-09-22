# tests/test_find_latest_file.py
# Guards the exact-date contract of find_latest_file: an earlier file
# must never be returned for a later run_date (stale-price duplication).
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_exact_date_only(tmp_path: Path):
    from src.scrapers.sbs import find_latest_file
    (tmp_path / "vector_completo").mkdir()
    (tmp_path / "vector_completo" / "20260918.xls").write_text("x")
    (tmp_path / "rfl").mkdir()
    (tmp_path / "rfl" / "20260918 RFL.xls").write_text("x")

    assert find_latest_file("vector_completo", date(2026, 9, 18), tmp_path).name == "20260918.xls"
    assert find_latest_file("rfl", date(2026, 9, 18), tmp_path).name == "20260918 RFL.xls"
    assert find_latest_file("vector_completo", date(2026, 9, 21), tmp_path) is None
    assert find_latest_file("missing_folder", date(2026, 9, 18), tmp_path) is None


if __name__ == "__main__":
    import tempfile
    test_exact_date_only(Path(tempfile.mkdtemp()))
    print("ok")
