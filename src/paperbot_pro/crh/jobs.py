"""Background backtest jobs: one worker thread per job, progress/stage/log,
cancellation, result reuse. Jobs never touch the live engines."""
from __future__ import annotations
import threading
import time
import traceback
import uuid

from .data import Cache
from .runner import RunStore, run_backtest

STAGES = ["universe", "candles", "prescan", "books", "replay", "report", "done"]


class Job:
    def __init__(self, params: dict, force: bool):
        self.id = uuid.uuid4().hex[:10]
        self.run_id = uuid.uuid4().hex[:12]
        self.params, self.force = params, force
        self.status = "queued"
        self.stage, self.fraction, self.detail = "queued", 0.0, None
        self.log: list[dict] = []
        self.error: str | None = None
        self.result_run_id: str | None = None
        self.reused = False
        self.created, self.started, self.finished = time.time(), None, None
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def progress(self, stage, fraction, detail=None):
        self.stage = stage
        if fraction is not None:
            self.fraction = float(fraction)
        if detail:
            self.detail = str(detail)
        if not self.log or self.log[-1]["stage"] != stage or (detail and self.log[-1].get("detail") != detail):
            self.log.append({"t": time.time(), "stage": stage, "detail": detail})
            self.log = self.log[-300:]

    def overall(self) -> float:
        if self.status == "done":
            return 1.0
        i = STAGES.index(self.stage) if self.stage in STAGES else 0
        return min(0.99, (i + self.fraction) / (len(STAGES) - 1))

    def snapshot(self) -> dict:
        return {"job_id": self.id, "status": self.status, "stage": self.stage,
                "fraction": self.fraction, "overall": self.overall(), "detail": self.detail,
                "run_id": self.result_run_id, "reused": self.reused, "error": self.error,
                "created": self.created, "started": self.started, "finished": self.finished,
                "params": self.params, "log": self.log[-40:]}


class JobManager:
    def __init__(self, store: RunStore, cache: Cache | None = None, max_parallel: int = 2):
        self.store, self.cache = store, cache or Cache()
        self.jobs: dict[str, Job] = {}
        self.sem = threading.Semaphore(max_parallel)
        self.lock = threading.Lock()

    def submit(self, params: dict, force: bool = False) -> Job:
        job = Job(params, force)
        with self.lock:
            self.jobs[job.id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _run(self, job: Job):
        with self.sem:
            if job.cancelled():
                job.status, job.finished = "cancelled", time.time()
                return
            job.status, job.started = "running", time.time()
            try:
                res = run_backtest(job.params, self.cache, self.store, job.progress,
                                   job.cancelled, run_id=job.run_id, force=job.force)
                job.result_run_id = res["run_id"]
                job.reused = bool(res.get("reused_from"))
                job.status = "done"
                job.progress("done", 1.0, "reused cached result" if job.reused else None)
            except Exception as exc:
                job.error = str(exc) or type(exc).__name__
                job.status = "cancelled" if job.error == "cancelled" else "failed"
                if job.status == "failed":
                    job.log.append({"t": time.time(), "stage": "error",
                                    "detail": traceback.format_exc()[-1500:]})
            finally:
                job.finished = time.time()

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if job is None or job.status in ("done", "failed", "cancelled"):
            return False
        job.cancel()
        return True

    def list(self) -> list[dict]:
        return [j.snapshot() for j in sorted(self.jobs.values(), key=lambda j: -j.created)]
