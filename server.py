"""Dev CockpitのHTTP APIと静的PWAサーバー。"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cockpit.config import load_config, make_agents, make_projects, make_router
from cockpit.core import JobManager


PUBLIC_DIR = Path(__file__).parent / "public"
MAX_BODY_BYTES = 1_000_000


class CockpitHandler(BaseHTTPRequestHandler):
    server_version = "DevCockpit/0.1"

    @property
    def manager(self) -> JobManager:
        return self.server.manager  # type: ignore[attr-defined]

    @property
    def token(self) -> str | None:
        return self.server.token  # type: ignore[attr-defined]

    def _authorized(self) -> bool:
        return not self.token or self.headers.get("Authorization") == f"Bearer {self.token}"

    def _json(self, payload: object, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
        self._json({"error": message}, status)

    def _body(self) -> dict[str, object]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length > MAX_BODY_BYTES:
            raise ValueError("request body is too large")
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        return data

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/") and not self._authorized():
            self._error("unauthorized", HTTPStatus.UNAUTHORIZED)
            return
        try:
            if parsed.path == "/api/health":
                self._json({"status": "ok"})
            elif parsed.path == "/api/projects":
                self._json([{"id": p.id, "name": p.name} for p in self.manager.projects.values()])
            elif parsed.path == "/api/agents":
                auto_agent = self.manager.router.auto_agent if self.manager.router is not None else None
                self._json([{"id": name, "name": "Auto (Jev)" if name == auto_agent else name} for name in self.manager.available_agents()])
            elif parsed.path == "/api/jobs":
                self._json([job.public() for job in self.manager.list_jobs()])
            elif parsed.path.startswith("/api/jobs/"):
                self._get_job(parsed.path, parse_qs(parsed.query))
            else:
                self._static(parsed.path)
        except (KeyError, ValueError, FileNotFoundError) as exc:
            status = HTTPStatus.NOT_FOUND if isinstance(exc, (KeyError, FileNotFoundError)) else HTTPStatus.BAD_REQUEST
            self._error(str(exc), status)
        except Exception as exc:  # noqa: BLE001 - HTTP境界でJSONエラーに変換する。
            self._error(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

    def _get_job(self, path: str, query: dict[str, list[str]]) -> None:
        parts = [part for part in path.split("/") if part]
        if len(parts) < 3:
            raise KeyError("job id is required")
        job = self.manager.get(parts[2])
        if len(parts) == 3:
            self._json(job.public(include_log=True))
        elif parts[3] == "diff":
            self._json(self.manager.diff(job.id))
        elif parts[3] == "file":
            relative_path = (query.get("path") or [""])[0]
            self._json({"path": relative_path, "content": self.manager.read_file(job.id, relative_path)})
        else:
            raise KeyError("unknown job resource")

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._error("unauthorized", HTTPStatus.UNAUTHORIZED)
            return
        parsed = urlparse(self.path)
        try:
            data = self._body()
            if parsed.path == "/api/jobs":
                job = self.manager.create(str(data.get("projectId", "")), str(data.get("agent", "")), str(data.get("prompt", "")))
                self._json(job.public(), HTTPStatus.ACCEPTED)
                return
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) < 3 or parts[0:2] != ["api", "jobs"]:
                raise KeyError("unknown endpoint")
            job_id = parts[2]
            if len(parts) == 4 and parts[3] == "stop":
                self._json(self.manager.stop(job_id).public())
            elif len(parts) == 4 and parts[3] == "follow-up":
                job = self.manager.get(job_id)
                follow_up = self.manager.create(job.project_id, job.agent, str(data.get("prompt", "")), parent_id=job_id)
                self._json(follow_up.public(), HTTPStatus.ACCEPTED)
            elif len(parts) == 4 and parts[3] == "approve":
                self._json(self.manager.approve(job_id, str(data.get("commitMessage", ""))).public())
            elif len(parts) == 4 and parts[3] == "push":
                self._json(self.manager.push(job_id).public())
            else:
                raise KeyError("unknown job action")
        except (KeyError, ValueError, FileNotFoundError) as exc:
            status = HTTPStatus.NOT_FOUND if isinstance(exc, (KeyError, FileNotFoundError)) else HTTPStatus.BAD_REQUEST
            self._error(str(exc), status)
        except Exception as exc:  # noqa: BLE001 - HTTP境界でJSONエラーに変換する。
            self._error(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_DELETE(self) -> None:  # noqa: N802
        if not self._authorized():
            self._error("unauthorized", HTTPStatus.UNAUTHORIZED)
            return
        parts = [part for part in urlparse(self.path).path.split("/") if part]
        try:
            if len(parts) != 3 or parts[0:2] != ["api", "jobs"]:
                raise KeyError("unknown endpoint")
            self.manager.discard(parts[2])
            self._json({"status": "discarded"})
        except (KeyError, ValueError, FileNotFoundError) as exc:
            status = HTTPStatus.NOT_FOUND if isinstance(exc, (KeyError, FileNotFoundError)) else HTTPStatus.BAD_REQUEST
            self._error(str(exc), status)
        except Exception as exc:  # noqa: BLE001
            self._error(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

    def _static(self, request_path: str) -> None:
        relative = request_path.lstrip("/") or "index.html"
        root, target = PUBLIC_DIR.resolve(), (PUBLIC_DIR / relative).resolve()
        if target != root and root not in target.parents:
            self._error("invalid path", HTTPStatus.BAD_REQUEST)
            return
        if not target.is_file():
            self._error("not found", HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        # AuthorizationヘッダーはHTTPアクセスログに含めない。
        super().log_message(format, *args)


def build_server(config_path: Path) -> ThreadingHTTPServer:
    config_path = config_path.expanduser().resolve()
    config = load_config(config_path)
    agents = make_agents(config)
    router = make_router(config, agents, config_path.parent)
    manager = JobManager(make_projects(config), agents, Path(config.get("jobs_root", config_path.parent / "runtime" / "jobs")).expanduser().resolve(), router=router)
    server = ThreadingHTTPServer((str(config.get("host", "127.0.0.1")), int(config.get("port", 8787))), CockpitHandler)
    server.manager = manager  # type: ignore[attr-defined]
    server.token = os.environ.get("DEV_COCKPIT_TOKEN")  # type: ignore[attr-defined]
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Dev Cockpit gateway")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    args = parser.parse_args()
    server = build_server(args.config)
    print(f"Dev Cockpit listening on http://{server.server_address[0]}:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
