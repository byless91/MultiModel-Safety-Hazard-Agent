"""R5/T13: disposable SQLite/PG Compose business loop and dependency failures."""

import argparse
import base64
import json
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jR1kAAAAASUVORK5CYII=")
SECRET = "r5-compose-local-signing-secret-at-least-32-bytes"
PASSWORD = "r5-compose-test-password"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=["sqlite", "pg"], required=True)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--backend-image", default="safety-r5-backend:test")
    parser.add_argument("--frontend-image", default="safety-r5-frontend:test")
    args = parser.parse_args()
    project = f"r5-smoke-{args.variant}-{uuid4().hex[:10]}"
    compose_file = ROOT / ("docker-compose.pg.yml" if args.variant == "pg" else "docker-compose.yml")
    command = ["docker", "compose", "-p", project, "-f", str(compose_file)]
    environment = {**os.environ, "BACKEND_IMAGE": args.backend_image, "FRONTEND_IMAGE": args.frontend_image,
                   "AUTH_MODE": "jwt", "AUTH_JWT_SECRET": SECRET, "API_BEARER_TOKEN": "",
                   "PROVIDER_MODE": "mock", "DASHSCOPE_API_KEY": "", "ZHIPU_API_KEY": "",
                   "WORKFLOW_MODE": "async", "RATE_LIMIT_ENABLED": "false",
                   "BACKEND_PORT": "0", "FRONTEND_PORT": "0",
                   "BACKEND_BIND_HOST": "127.0.0.1", "FRONTEND_BIND_HOST": "127.0.0.1"}

    def compose(*arguments, input=None, check=True):
        result = subprocess.run([*command, *arguments], env=environment, cwd=ROOT, input=input, capture_output=True,
                                text=True, encoding="utf-8", timeout=240)
        if check and result.returncode:
            raise RuntimeError(f"Compose command failed: {arguments}: {result.stdout[-3000:]} {result.stderr[-3000:]}")
        return result

    def url(service, port):
        address = compose("port", service, str(port)).stdout.strip().splitlines()[0]
        return f"http://{address}"

    try:
        print(f"R5 {args.variant}: starting isolated Compose stack", flush=True)
        up_args = ["up", "-d", "--wait", "--wait-timeout", "120"]
        compose(*up_args, *(["--build"] if args.build else ["--no-build"]))
        backend_url, frontend_url = url("backend", 8001), url("frontend", 80)
        with httpx.Client(base_url=frontend_url, trust_env=False, timeout=15) as client:
            assert "基层安全隐患" in client.get("/").text
            ready = client.get("/api/v1/ready")
            assert ready.status_code == 200 and all(ready.json()["checks"].values()), ready.text
            assert ready.json()["knowledge_scope"] == "development_seed_unreviewed"
            assert client.get("/api/v1/health").json()["provider"] == "mock"
            compose("exec", "-T", "backend", "python", "-m", "app.cli.create_user", "--username", "smoke-admin",
                    "--role", "admin", "--password-stdin", input=PASSWORD + "\n")
            login = client.post("/api/v1/auth/token", data={"username": "smoke-admin", "password": PASSWORD})
            assert login.status_code == 200, login.text
            client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
            key = f"compose-{uuid4().hex}"
            created = client.post("/api/v1/assessments", headers={"Idempotency-Key": key},
                                  data={"description": "小区楼道堆放纸箱杂物，堵塞疏散通道，通行明显受阻"},
                                  files={"files": ("scene.png", PNG, "image/png")})
            assert created.status_code == 202, created.text
            item_id, job_id = created.json()["assessment_id"], created.json()["id"]
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                job = client.get(f"/api/v1/assessments/{item_id}/job").json()
                if job["status"] in {"succeeded", "failed"}:
                    break
                time.sleep(0.2)
            assert job["status"] == "succeeded", job
            item = client.get(f"/api/v1/assessments/{item_id}").json()
            assert item["evidence"] and item["images"]
            photo_url = item["images"][0]["url"]
            assert client.get(photo_url).content == PNG
            unsigned = client.get(photo_url.split("?")[0])
            assert unsigned.status_code == 401
            confirmed = client.post(f"/api/v1/assessments/{item_id}/confirm",
                                    json={"confirmed": True, "reviewer": "伪造名"})
            assert confirmed.status_code == 200 and confirmed.json()["confirmed"]
            assert confirmed.json()["human_review"]["resolution"]["reviewer"] == "smoke-admin"
            exported = client.get(f"/api/v1/assessments/{item_id}/export")
            assert exported.status_code == 200 and exported.json()["content"]
            assert exported.json()["filename"] == f"{item_id}.md"
            content = "疏散通道保持畅通，禁止堆放杂物。".encode()
            document = client.post("/api/v1/knowledge/documents", data={"title": "持久化测试", "source": "R5测试"},
                                   files={"file": ("persistent.txt", content, "text/plain")})
            assert document.status_code == 201, document.text
            document_id = document.json()["id"]
            print(f"R5 {args.variant}: submit/query/review/export and signed image passed", flush=True)
            # Stop/restart the whole stack, including PG, on the same owned volumes.
            compose("stop")
            compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "120")
            backend_url, frontend_url = url("backend", 8001), url("frontend", 80)
            client.base_url = frontend_url  # Ephemeral host ports can change when Docker restarts a container.
            assert client.get(f"/api/v1/assessments/{item_id}").json()["confirmed"]
            assert client.get(photo_url).content == PNG
            assert client.get(f"/api/v1/knowledge/documents/{document_id}").status_code == 200
            assert client.get(f"/api/v1/assessments/{item_id}/job").json()["id"] == job_id
            # Persistent corpus loss must be visible even while the in-memory index exists.
            hide = ("from pathlib import Path; r=Path('/app/data/knowledge'); "
                    "[p.rename(p.with_suffix('.r5-hidden')) for p in "
                    "[*r.glob('*.jsonl'),*r.glob('chunks/*.jsonl')]]")
            restore = ("from pathlib import Path; r=Path('/app/data/knowledge'); "
                       "[p.rename(p.with_suffix('.jsonl')) for p in r.rglob('*.r5-hidden')]")
            compose("exec", "-T", "backend", "python", "-c", hide)
            try:
                unavailable = client.get("/api/v1/ready")
                assert unavailable.status_code == 503 and not unavailable.json()["checks"]["knowledge"]
                assert client.get("/api/v1/live").status_code == 200
                assert client.get("/api/v1/health").status_code == 200
            finally:
                compose("exec", "-T", "backend", "python", "-c", restore)
            assert client.get("/api/v1/ready").status_code == 200
            failure = compose("exec", "-T", "backend", "python", "-c",
                              "import app.core.db as d; "
                              "d.upgrade_to_head=lambda _: "
                              "(_ for _ in ()).throw(RuntimeError('r5-migration-failure')); "
                              "d.init_db()", check=False)
            assert failure.returncode != 0 and "r5-migration-failure" in failure.stderr
        with httpx.Client(trust_env=False, timeout=5) as direct:
            assert direct.get(f"{backend_url}/api/v1/ready").status_code == 200
        reports = ROOT / "test/.artifacts/reports"
        reports.mkdir(parents=True, exist_ok=True)
        (reports / f"r5-compose-{args.variant}.json").write_text(json.dumps({
            "passed": True, "variant": args.variant, "provider": "mock", "fresh_volumes": True,
            "ready_dependency": True, "submit_query_review_export": True, "signed_image_proxy": True,
            "restart_preserves_assessment_image_user_knowledge": True, "corpus_loss_returns_503": True,
            "liveness_survives_dependency_failure": True, "migration_failure_propagates": True,
        }, indent=2) + "\n", encoding="utf-8")
        print(f"R5 {args.variant}: persistence and readiness failure checks passed", flush=True)
    except Exception:
        print(compose("logs", "--tail", "25", check=False).stdout[-10000:], flush=True)
        raise
    finally:
        assert project.startswith(f"r5-smoke-{args.variant}-")
        # Compose scopes removal to this freshly generated project and its named volumes.
        compose("down", "--volumes", "--remove-orphans", check=False)


if __name__ == "__main__":
    main()
