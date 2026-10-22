import concurrent.futures

from stripsafe.workers import WorkerPool, inspect_job, process_job


def test_jobs_run_in_a_separate_process(tmp_path, jpeg_with_metadata):
    src = tmp_path / "a.jpg"
    src.write_bytes(jpeg_with_metadata)
    pool = WorkerPool(max_workers=2)
    try:
        report, thumb = pool.submit(inspect_job, src).result(timeout=60)
        assert dict(report.fields)["Camera make"] == "SpyCam Inc" and thumb is not None
        result = pool.submit(process_job, src, "balanced", None).result(timeout=60)
        assert result.ok and result.output == tmp_path / "a_clean.jpg"
    finally:
        pool.shutdown()


def test_pool_recovers_after_a_worker_dies(tmp_path):
    import os
    pool = WorkerPool(max_workers=1)
    try:
        crash = pool.submit(os._exit, 1)
        try:
            crash.result(timeout=60)
        except concurrent.futures.BrokenExecutor:
            pass
        (tmp_path / "x.txt").write_text("hi")
        result = pool.submit(process_job, tmp_path / "x.txt", "balanced", None).result(timeout=60)
        assert not result.ok  # unsupported type is reported, but the pool works again
    finally:
        pool.shutdown()
