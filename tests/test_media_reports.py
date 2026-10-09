from datetime import date, timedelta

import cv2
import pytest

from erp.services.analytics import collect_report_data
from erp.services.reports import build_flash_report
from erp.services.simulation_media import render_site_photo
from erp.services.timelapse import Frame, build_timelapse
from tests.conftest import TODAY


def _frames(n=5):
    return [Frame(date(2026, 1, 1) + timedelta(days=7 * i), "Estrutura",
                  render_site_photo(date(2026, 1, 1) + timedelta(days=7 * i), 1, i * 2, i, 0, "Estrutura"))
            for i in range(n)]


def test_timelapse_generates_valid_mp4(tmp_path):
    data = build_timelapse(_frames(), fps=10, seconds_per_photo=0.3, size=(640, 360))
    assert data[4:8] == b"ftyp"
    path = tmp_path / "v.mp4"
    path.write_bytes(data)
    cap = cv2.VideoCapture(str(path))
    assert cap.isOpened()
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    assert count >= 5 * 3
    ok, frame = cap.read()
    assert ok and frame.shape[:2] == (360, 640)


def test_timelapse_without_valid_photos():
    with pytest.raises(ValueError):
        build_timelapse([Frame(date.today(), "x", b"invalido")])


def test_flash_report_pdf_in_memory(seeded):
    import time

    data = collect_report_data(TODAY, user="admin")
    t0 = time.perf_counter()
    pdf = build_flash_report(data)
    elapsed = time.perf_counter() - t0
    assert pdf.startswith(b"%PDF") and len(pdf) > 3000
    assert elapsed < 3.0
