import os
import time

from app import engine


def test_downtime_reads_how_long_the_state_file_was_untouched(tmp_path):
    f = tmp_path / "trader.json"
    f.write_text("{}")
    assert engine._downtime(f) is None  # 방금 쓴 파일이면 꺼져 있던 게 아니다
    old = time.time() - 26 * 3600
    os.utime(f, (old, old))
    assert engine._downtime(f) == "1일 2시간"
    assert engine._downtime(tmp_path / "없음.json") is None
