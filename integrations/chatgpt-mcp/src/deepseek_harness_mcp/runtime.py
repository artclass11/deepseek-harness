from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig, UserQuestionAnswer, UserQuestionRequest

from .config import BridgeConfig
from .workspace import resolve_workspace, validate_session_id

_LOG = logging.getLogger(__name__)
_MAX_TASK_CHARS = 20_000
_MAX_OUTPUT_CHARS = 24_000


def validate_task_prompt(task: str) -> str:
    prompt = task.strip()
    if not prompt:
        raise ValueError("task must not be empty")
    if len(prompt) > _MAX_TASK_CHARS:
        raise ValueError(f"task must be at most {_MAX_TASK_CHARS} characters")
    return prompt


def validate_question_answers(
    questions: list[dict[str, Any]], answers: list[dict[str, Any]]
) -> dict[str, Any]:
    expected = {
        question.get("id")
        for question in questions
        if isinstance(question.get("id"), str)
    }
    parsed = UserQuestionAnswer.model_validate({"answers": answers})
    received = [answer.id for answer in parsed.answers]
    if len(received) != len(set(received)) or set(received) != expected:
        raise ValueError("answers must contain exactly one answer for each original question id")
    return parsed.model_dump(exclude_none=True, by_alias=True)


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    session_id: str
    workspace: str
    prompt: str
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    finish_reason: str | None = None
    final_response: str = ""
    error: str | None = None
    last_activity: str | None = None
    thread: threading.Thread | None = None


@dataclass(slots=True)
class ApprovalRecord:
    approval_id: str
    protocol_id: str | int
    session_id: str
    tool_name: str
    reason: str
    created_at: float = field(default_factory=time.time)
    decision_event: threading.Event = field(default_factory=threading.Event)
    approved: bool = False
    decided: bool = False


@dataclass(slots=True)
class QuestionRecord:
    request_id: str
    session_id: str
    questions: list[dict[str, Any]]
    created_at: float = field(default_factory=time.time)
    response: dict[str, Any] | None = None


class HarnessRuntime:
    """Own one local Harness SDK process and a bounded, workspace-scoped task queue."""

    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._harness: DeepSeekHarness | None = None
        self._approval_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._tasks: dict[str, TaskRecord] = {}
        self._session_handles: dict[str, Any] = {}
        self._approvals: dict[str, ApprovalRecord] = {}
        self._questions: dict[str, QuestionRecord] = {}
        self._sessions_file = config.dsh_home / "chatgpt-bridge-sessions.json"
        self._sessions = self._read_sessions()

    def health_check(self) -> dict[str, Any]:
        harness = self._ensure_started()
        return {
            "status": "ready",
            "runtime": "deepseek-harness-sdk",
            "profile": harness.config.profile,
            "model": harness.config.model,
            "workspace_root": str(self.config.workspace_root),
            "session_persistence": str(self.config.dsh_home / "sessions"),
            "approval_requests": True,
        }

    def start_task(self, task: str, workspace_path: str = "") -> dict[str, Any]:
        return self._submit(task, workspace_path=workspace_path, resume=False)

    def resume_session(self, session_id: str, task: str) -> dict[str, Any]:
        valid_id = validate_session_id(session_id)
        with self._lock:
            if valid_id not in self._sessions:
                raise ValueError("session_id is not registered by this bridge")
            workspace = self._sessions[valid_id]["workspace"]
        return self._submit(task, workspace_path=workspace, session_id=valid_id, resume=True)

    def _submit(
        self,
        task: str,
        *,
        workspace_path: str = "",
        session_id: str | None = None,
        resume: bool,
    ) -> dict[str, Any]:
        prompt = validate_task_prompt(task)
        workspace = resolve_workspace(workspace_path, self.config.workspace_root)
        self._ensure_started()

        with self._lock:
            active = sum(item.status in {"queued", "running"} for item in self._tasks.values())
            if active >= self.config.max_active_tasks:
                raise RuntimeError("the local Harness bridge is busy; wait for the active task to finish")
            chosen_session = validate_session_id(session_id) if session_id else f"session-{uuid.uuid4().hex}"
            if resume and chosen_session not in self._sessions:
                raise ValueError("session_id is not registered by this bridge")
            if not resume and chosen_session in self._sessions:
                raise ValueError("session_id is already registered; use resume_session")
            task_id = uuid.uuid4().hex
            record = TaskRecord(task_id, chosen_session, str(workspace), prompt)
            self._tasks[task_id] = record
            self._sessions[chosen_session] = {
                "workspace": str(workspace),
                "created_at": self._sessions.get(chosen_session, {}).get("created_at", time.time()),
                "updated_at": time.time(),
            }
            self._write_sessions()
            worker = threading.Thread(
                target=self._run_task,
                args=(record, resume),
                name=f"dsh-task-{task_id[:8]}",
                daemon=True,
            )
            record.thread = worker
            worker.start()
        return {"task_id": task_id, "session_id": chosen_session, "status": "queued"}

    def _run_task(self, record: TaskRecord, resume: bool) -> None:
        with self._lock:
            record.status = "running"
            record.updated_at = time.time()
        try:
            harness = self._ensure_started()
            with self._lock:
                session = self._session_handles.get(record.session_id)
            if session is None:
                session = (
                    harness.resume_session(record.session_id)
                    if resume
                    else harness.start_session(record.session_id)
                )
                with self._lock:
                    self._session_handles[record.session_id] = session
            session.set_working_directory(record.workspace)
            result = session.run(record.prompt, on_notification=lambda notification: self._on_notification(record, notification))
            with self._lock:
                record.final_response = result.final_response[-_MAX_OUTPUT_CHARS:]
                record.finish_reason = result.finish_reason
                record.status = (
                    "completed" if result.finish_reason == "completed"
                    else "partial" if result.finish_reason == "max-tokens"
                    else "failed"
                )
                record.updated_at = time.time()
                self._sessions[record.session_id]["updated_at"] = record.updated_at
                self._write_sessions()
        except Exception as exc:
            _LOG.exception("Harness task failed (task_id=%s)", record.task_id)
            with self._lock:
                record.error = f"{type(exc).__name__}: {exc}"[:4000]
                record.status = "failed"
                record.updated_at = time.time()

    def _on_notification(self, record: TaskRecord, notification: Any) -> None:
        with self._lock:
            record.last_activity = notification.method
            record.updated_at = time.time()

    def task_status(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._get_task(task_id)
            return {
                "task_id": record.task_id,
                "session_id": record.session_id,
                "status": record.status,
                "finish_reason": record.finish_reason,
                "workspace": record.workspace,
                "last_activity": record.last_activity,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }

    def task_output(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._get_task(task_id)
            return {
                "task_id": record.task_id,
                "session_id": record.session_id,
                "status": record.status,
                "finish_reason": record.finish_reason,
                "final_response": record.final_response,
                "error": record.error,
            }

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"session_id": session_id, **metadata}
                for session_id, metadata in sorted(
                    self._sessions.items(),
                    key=lambda item: item[1].get("updated_at", 0),
                    reverse=True,
                )[:50]
            ]

    def set_working_directory(self, session_id: str, path: str) -> dict[str, Any]:
        valid_id = validate_session_id(session_id)
        with self._lock:
            if valid_id not in self._sessions:
                raise ValueError("session_id is not registered by this bridge")
            if any(
                task.session_id == valid_id and task.status in {"queued", "running"}
                for task in self._tasks.values()
            ):
                raise RuntimeError("cannot change the working directory while this session is running")
        workspace = resolve_workspace(path, self.config.workspace_root)
        harness = self._ensure_started()
        with self._lock:
            session = self._session_handles.get(valid_id)
        if session is None:
            session = harness.resume_session(valid_id)
            with self._lock:
                self._session_handles[valid_id] = session
        resolved = session.set_working_directory(str(workspace))
        with self._lock:
            self._sessions[valid_id]["workspace"] = resolved
            self._sessions[valid_id]["updated_at"] = time.time()
            self._write_sessions()
        return {"session_id": valid_id, "workspace": resolved}

    def pending_approvals(self) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            return [
                {
                    "approval_id": item.approval_id,
                    "session_id": item.session_id,
                    "tool_name": item.tool_name,
                    "reason": item.reason,
                    "expires_in_seconds": max(0, int(self.config.approval_timeout_seconds - (now - item.created_at))),
                }
                for item in self._approvals.values()
                if not item.decided and now - item.created_at < self.config.approval_timeout_seconds
            ]

    def decide_approval(self, approval_id: str, approved: bool) -> dict[str, Any]:
        if not isinstance(approved, bool):
            raise ValueError("approved must be true or false")
        with self._lock:
            item = self._approvals.get(approval_id)
            if item is None:
                raise ValueError("unknown approval_id")
            if item.decided or item.decision_event.is_set():
                raise ValueError("approval has already been decided")
            if time.time() - item.created_at >= self.config.approval_timeout_seconds:
                item.decided = True
                item.decision_event.set()
                raise TimeoutError("approval expired and will be rejected")
            item.approved = approved
            item.decided = True
            item.decision_event.set()
        return {"approval_id": approval_id, "decision": "allowed-once" if approved else "rejected"}

    def pending_questions(self) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            return [
                {
                    "request_id": item.request_id,
                    "session_id": item.session_id,
                    "questions": item.questions,
                    "expires_in_seconds": max(0, int(self.config.question_timeout_seconds - (now - item.created_at))),
                }
                for item in self._questions.values()
                if item.response is None and now - item.created_at < self.config.question_timeout_seconds
            ]

    def answer_question(self, request_id: str, answers: list[dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            item = self._questions.get(request_id)
            if item is None or item.response is not None:
                raise ValueError("unknown or already answered request_id")
            if time.time() - item.created_at >= self.config.question_timeout_seconds:
                raise TimeoutError("question expired; the runtime will treat it as cancelled")
            response = validate_question_answers(item.questions, answers)
            item.response = response
            self._condition.notify_all()
        return {"request_id": request_id, "status": "answered"}

    def _get_task(self, task_id: str) -> TaskRecord:
        record = self._tasks.get(task_id)
        if record is None:
            raise ValueError("unknown task_id; task records are held in memory until the bridge restarts")
        return record

    def _read_sessions(self) -> dict[str, dict[str, Any]]:
        if not self._sessions_file.exists():
            return {}
        try:
            raw = json.loads(self._sessions_file.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return {}
            valid: dict[str, dict[str, Any]] = {}
            for session_id, item in raw.items():
                if isinstance(session_id, str) and isinstance(item, dict):
                    workspace = resolve_workspace(str(item.get("workspace", "")), self.config.workspace_root)
                    valid[validate_session_id(session_id)] = {
                        "workspace": str(workspace),
                        "created_at": float(item.get("created_at", time.time())),
                        "updated_at": float(item.get("updated_at", time.time())),
                    }
            return valid
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            _LOG.exception("Unable to load the bridge session index; refusing to trust its contents")
            return {}

    def _write_sessions(self) -> None:
        self._sessions_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._sessions_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._sessions, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self._sessions_file)

    def _ensure_started(self) -> DeepSeekHarness:
        with self._lock:
            if self._harness is not None:
                return self._harness
            harness = DeepSeekHarness(
                DeepSeekHarnessConfig(
                    provider="deepseek-official",
                    model=self.config.model,
                    reasoning_effort=self.config.reasoning_effort,
                    max_tokens=self.config.max_tokens,
                    cwd=str(self.config.workspace_root),
                    profile="sdk",
                    dsh_home=str(self.config.dsh_home),
                    env={"DSH_TELEMETRY_DISABLED": "1"},
                    approval_requests=True,
                    on_user_question=self._handle_user_question,
                )
            )
            harness.start()
            self._harness = harness
            self._stop.clear()
            self._approval_thread = threading.Thread(
                target=self._approval_loop,
                name="dsh-approval-requests",
                daemon=True,
            )
            self._approval_thread.start()
            return harness

    def _approval_loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                harness = self._harness
            if harness is None:
                return
            try:
                request = harness.client.next_request()
            except Exception:
                if not self._stop.is_set():
                    _LOG.exception("Harness approval request reader stopped")
                return
            if request.method != "approval/request":
                try:
                    harness.client.respond_error(
                        request.id, code=-32601, message="Unsupported Harness client request"
                    )
                except Exception:
                    _LOG.exception("Unable to reject an unsupported Harness request")
                continue

            payload = request.payload
            approval_id = uuid.uuid4().hex
            record = ApprovalRecord(
                approval_id=approval_id,
                protocol_id=request.id,
                session_id=str(payload.get("sessionId", "")),
                tool_name=str(payload.get("toolName", "")),
                reason=str(payload.get("reason", "")),
            )
            with self._lock:
                self._approvals[approval_id] = record
            decided = record.decision_event.wait(self.config.approval_timeout_seconds)
            outcome = "allowed-once" if decided and record.decided and record.approved else "rejected"
            try:
                harness.client.respond(request.id, {"outcome": outcome})
            except Exception:
                _LOG.exception("Unable to send fail-closed approval response")
            finally:
                with self._lock:
                    self._approvals.pop(approval_id, None)

    def _handle_user_question(
        self, request: UserQuestionRequest, cancelled: threading.Event
    ) -> dict[str, Any]:
        item = QuestionRecord(
            request_id=request.request_id,
            session_id=request.session_id,
            questions=request.questions,
        )
        with self._condition:
            self._questions[item.request_id] = item
            deadline = time.monotonic() + self.config.question_timeout_seconds
            while not cancelled.is_set() and item.response is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._questions.pop(item.request_id, None)
                    return {"cancelled": True}
                self._condition.wait(timeout=min(remaining, 0.25))
            if item.response is None:
                self._questions.pop(item.request_id, None)
                return {"cancelled": True}
            return item.response

    def close(self) -> None:
        self._stop.set()
        with self._condition:
            for item in self._questions.values():
                if item.response is None:
                    item.response = {"cancelled": True}
            self._condition.notify_all()
            for item in self._approvals.values():
                item.approved = False
                item.decided = True
                item.decision_event.set()
        if self._harness is not None:
            self._harness.close()
            self._harness = None
