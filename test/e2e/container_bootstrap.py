"""R5/T12: disposable image + empty volume, operator login and restart preservation."""

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]
LABEL = "safety-hazard-test=r5-bootstrap"
PASSWORD = "r5-local-admin-password"
SECRET = "r5-local-test-signing-secret-at-least-32-bytes"


def docker(*args, input=None):
    result = subprocess.run(["docker", *args], input=input, text=True, encoding="utf-8",
                            capture_output=True, check=True, timeout=90)
    return result.stdout.strip()


def wait_health(url, container):
    deadline = time.monotonic() + 45
    with httpx.Client(trust_env=False, timeout=3) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get(f"{url}/api/v1/health")
                if response.status_code == 200:
                    return response.json()
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
    raise AssertionError(f"container failed to start: {docker('logs', '--tail', '30', container)}")


def snapshot(container):
    code = (
        "import hashlib,json,pathlib; root=pathlib.Path('/app/data/knowledge');"
        "files={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() "
        "for p in root.rglob('*') if p.is_file()};"
        "seed=pathlib.Path('/app/resources/knowledge_seed');"
        "print(json.dumps({'files':files,'seed_readonly':all(not(p.stat().st_mode&0o222) "
        "for p in seed.rglob('*') if p.is_file())}))"
    )
    return json.loads(docker("exec", container, "python", "-c", code))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="safety-r5-backend:test")
    args = parser.parse_args()
    suffix = uuid4().hex[:10]
    container, volume = f"r5-bootstrap-{suffix}", f"r5-bootstrap-data-{suffix}"
    docker("volume", "create", "--label", LABEL, volume)

    def start():
        docker("run", "-d", "--name", container, "--label", LABEL, "-p", "127.0.0.1::8001",
               "--mount", f"type=volume,source={volume},target=/app/data",
               "-e", "AUTH_MODE=jwt", "-e", f"AUTH_JWT_SECRET={SECRET}",
               "-e", "DASHSCOPE_API_KEY=", "-e", "ZHIPU_API_KEY=", args.image)
        port = json.loads(docker("inspect", container))[0]["NetworkSettings"]["Ports"]["8001/tcp"][0]["HostPort"]
        return f"http://127.0.0.1:{port}"

    try:
        url = start()
        health = wait_health(url, container)
        assert health["provider"] == "mock" and health["rag_loaded"]
        initial = snapshot(container)
        assert initial["seed_readonly"] and "chunks/real_chunks.jsonl" in initial["files"]
        assert ".bootstrap.json" in initial["files"]
        output = docker("exec", "-i", container, "python", "-m", "app.cli.create_user", "--username", "bootstrap-admin",
                        "--role", "admin", "--password-stdin", input=PASSWORD + "\n")
        assert PASSWORD not in output
        with httpx.Client(base_url=url, trust_env=False, timeout=15) as client:
            login = client.post("/api/v1/auth/token", data={"username": "bootstrap-admin", "password": PASSWORD})
            assert login.status_code == 200, login.text
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            assert client.get("/api/v1/auth/me", headers=headers).json()["role"] == "admin"
            content = "楼道通道应保持畅通，发现纸箱堆放应及时清理。".encode()
            document = client.post("/api/v1/knowledge/documents", headers=headers,
                                   data={"title": "运维上传测试", "source": "R5离线测试"},
                                   files={"file": ("operator.txt", content, "text/plain")})
            assert document.status_code == 201, document.text
            document_id = document.json()["id"]
        before = snapshot(container)
        docker("stop", "-t", "10", container)
        docker("rm", container)
        url = start()  # New container, same data volume: deployment replacement.
        assert wait_health(url, container)["rag_loaded"]
        assert snapshot(container) == before
        with httpx.Client(base_url=url, trust_env=False, timeout=15) as client:
            login = client.post("/api/v1/auth/token", data={"username": "bootstrap-admin", "password": PASSWORD})
            assert login.status_code == 200
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            detail = client.get(f"/api/v1/knowledge/documents/{document_id}", headers=headers)
            assert detail.status_code == 200 and detail.json()["id"] == document_id
        reports = ROOT / "test/.artifacts/reports"
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "r5-container-bootstrap.json").write_text(json.dumps({
            "passed": True, "image": args.image, "fresh_volume": True, "provider": health["provider"],
            "seed_readonly": True, "seed_scope": "development_excerpt/unreviewed", "operator_cli_login": True,
            "container_recreated": True, "knowledge_and_users_preserved": True,
            "knowledge_snapshot_sha256": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
        }, indent=2) + "\n", encoding="utf-8")
        print("R5 container bootstrap passed: searchable fresh volume, admin login; replacement preserves data")
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)
        label = docker("volume", "inspect", "--format", '{{index .Labels "safety-hazard-test"}}', volume)
        assert label == "r5-bootstrap", "refusing to remove an unowned volume"
        docker("volume", "rm", volume)


if __name__ == "__main__":
    main()
