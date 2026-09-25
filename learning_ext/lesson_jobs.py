from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import monotonic
import logging

from learning_ext.progress.study import generate_node_summary_to_db

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lesson-generation")
_lock = Lock()
_jobs = {}
log = logging.getLogger(__name__)


def enqueue(node_id, topic, force=False):
    node_id = int(node_id)
    with _lock:
        old = _jobs.get(node_id)
        if old and (old["status"] in {"queued", "running"} or not force):
            return
        job = {"status": "queued", "started": None, "error": ""}
        _jobs[node_id] = job
        _pool.submit(_run, node_id, topic, force, job)


def _run(node_id, topic, force, job):
    with _lock:
        job.update(status="running", started=monotonic())
    log.info("课节正文开始 node=%s", node_id)
    try:
        ok = generate_node_summary_to_db(node_id, topic, force=force, raise_on_error=True)
    except Exception as exc:
        log.exception("课节正文异常 node=%s", node_id)
        job["error"] = f"{type(exc).__name__}: {exc}"[:300]
        ok = False
    with _lock:
        job["status"] = "ready" if ok else "failed"
    log.info("课节正文结束 node=%s status=%s elapsed=%.1fs", node_id, job["status"], monotonic()-job["started"])


def status(node_id):
    with _lock:
        job = dict(_jobs.get(int(node_id), {})) if node_id else {}
    labels = {"queued": "等待后台生成", "running": "正在后台生成正文", "ready": "正文已生成，可点击刷新正文", "failed": "生成失败，请点击重新生成本节重试"}
    result = labels.get(job.get("status"), "")
    if job.get("status") == "running":
        result += f"（已用 {int(monotonic()-job['started'])} 秒，包含可能的网络重试）"
    if job.get("status") == "failed" and job.get("error"):
        result += f"（原因：{job['error']}）"
    return result
