#!/usr/bin/env python3
"""Build/smoke the production image and reuse one data volume across two containers.

The stored marker and empty index range are serialization fixtures, not chain responses.
A fresh accounts-zero Anvil supplies real chain identity reads. No fork, credentials or transaction is used. Test containers/volume are retained.
"""
import argparse
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
import socket
import time
from pathlib import Path


def configured_storage():
    entry = Path(__file__).with_name("entrypoint.sh").read_text()
    arguments = shlex.split(entry.split("exec python3 ", 1)[1].replace("\\\n", " "))
    state = Path(arguments[arguments.index("--state") + 1])
    index = Path(arguments[arguments.index("--index") + 1])
    # The index argument is the directory holding one index file per account.
    assert state.parent == index == Path("/data"), "both stores must use the persistent mount"
    return state, index


def persistence(mode, directory):
    from eth_utils import keccak
    from index import EventIndex
    from tx import TxManager

    assert keccak(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    directory.mkdir(parents=True, exist_ok=True)
    state, index = configured_storage()
    state_path = directory / state.name
    vault = "0x0000000000000000000000000000000000001234"
    index_path = directory / f'index-{vault.lower()}.sqlite'
    if mode == "seed":
        assert not state_path.exists() and not index_path.exists(), "use a fresh test volume"
    # The production constructor validates chain identity. Read a real isolated node instead
    # of supplying a successful RPC answer or bypassing that validation for serialization.
    with socket.socket() as available:
        available.bind(('127.0.0.1',0))
        port=available.getsockname()[1]
    rpc=f'http://127.0.0.1:{port}'
    node=subprocess.Popen(['anvil','--host','127.0.0.1','--port',str(port),'--chain-id','31337','--accounts','0','--silent'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            ready=subprocess.run(['cast','chain-id','--rpc-url',rpc],capture_output=True,text=True)
            if ready.returncode==0:
                assert int(ready.stdout.strip())==31337
                break
            if node.poll() is not None:
                raise RuntimeError('packaging identity node exited before readiness')
            time.sleep(.05)
        else:
            raise RuntimeError('packaging identity node did not become ready')
        manager = TxManager(rpc, str(state_path), vault, [], log=lambda _: None)
    finally:
        node.terminate()
        node.wait(10)
    book = EventIndex(index_path, 1, vault, 100)
    if mode == "seed":
        manager.state["packaging_marker"] = "persisted"
        manager.save()
        assert book.append(100, 104, "local-serialization-fixture", [])
    else:
        assert manager.state["packaging_marker"] == "persisted"
        assert book.head == 104
        for chain, address, deployment in ((2, vault, 100), (1, "0x0000000000000000000000000000000000005678", 100),
                                            (1, vault, 101)):
            try:
                EventIndex(index_path, chain, address, deployment)
            except ValueError:
                pass
            else:
                raise AssertionError("persisted index accepted another identity")
    assert book.head == 104
    assert manager.state["stats"]["mined"] == 0
    assert manager.state["pending"] is None
    book.close()
    manager._lockf.close()
    print(json.dumps({"mode": mode, "directory": str(directory), "index_head": 104,
                      "transaction_marker": "persisted", "chain_identity": "real isolated accounts-zero Anvil", "broadcasts": 0}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", help="existing production image; omit to build keeper/Dockerfile")
    parser.add_argument("--host-persistence", action="store_true", help="two-process storage test only, not container proof")
    parser.add_argument("--seed-projection", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--verify-projection", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.seed_projection or args.verify_projection:
        persistence("seed" if args.seed_projection else "verify", args.seed_projection or args.verify_projection)
        return
    root = Path(__file__).resolve().parent.parent
    configured_storage()
    import tomllib
    for name in ("fly.keeper-primary.toml", "fly.keeper-backup.toml"):
        config = tomllib.loads((root / name).read_text())
        assert config["build"]["dockerfile"] == "keeper/Dockerfile"
        assert config["mounts"]["destination"] == "/data"
    if args.host_persistence:
        data = Path(tempfile.mkdtemp(prefix="review-packaging-storage-"))
        for phase in ("seed", "verify"):
            subprocess.run([sys.executable, __file__, f"--{phase}-projection", str(data)], check=True)
        print("PASS: host process replacement only; Docker image/volume replacement remains separate")
        return
    if shutil.which("docker") is None:
        raise SystemExit("Docker is unavailable; production image and container replacement were not tested")
    subprocess.run(["docker", "info"], check=True, stdout=subprocess.DEVNULL)
    suffix = uuid.uuid4().hex[:10]
    image = args.image or f"packvault-keeper-review:{suffix}"
    if not args.image:
        subprocess.run(["docker", "build", "--platform", "linux/amd64", "-f", "keeper/Dockerfile", "-t", image, "."],
                       cwd=root, check=True)
    subprocess.run(["docker", "run", "--platform", "linux/amd64", "--name", f"packvault-smoke-{suffix}",
                    "--entrypoint", "python3", image, "keeper/keeper.py", "--help"], check=True)
    volume = f"packvault-persistence-{suffix}"
    subprocess.run(["docker", "volume", "create", volume], check=True)
    for phase in ("seed", "verify"):
        subprocess.run(["docker", "run", "--platform", "linux/amd64", "--name", f"packvault-{phase}-{suffix}",
                        "--mount", f"type=volume,source={volume},target=/data", "--entrypoint", "python3", image,
                        "keeper/test_packaging.py", f"--{phase}-projection", "/data"], check=True)
    containers = [subprocess.check_output(["docker", "inspect", "--format", "{{.Id}}",
                                          f"packvault-{phase}-{suffix}"], text=True).strip()
                  for phase in ("seed", "verify")]
    assert len(set(containers)) == 2, "persistence must survive separate container instances"
    image_id = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", image], text=True).strip()
    print(json.dumps({"result": "PASS", "image": image, "volume": volume, "retained": True,
                      "image_id": image_id, "containers": containers,
                      "scope": "actual image smoke and separate containers sharing /data; no network transactions"}))


if __name__ == "__main__":
    main()
