#!/usr/bin/env python3
import json
import socket
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

RPC_SOURCES = [
    "https://rpc.test13.testnets.gno.land",
    "http://[2a03:cfc0:8000:13::b910:27ac]:54657",
]

HTTP_TIMEOUT = 5
TCP_TIMEOUT = 3
HISTORY_WINDOW = 10
UPTIME_THRESHOLD = 0.70

DATA_DIR = Path(__file__).resolve().parent
HISTORY_FILE = DATA_DIR / "history.json"
OUTPUT_FILE = DATA_DIR / "peers.json"


def fetch_net_info(rpc_url: str):
    url = rpc_url.rstrip("/") + "/net_info"
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"[warn] {rpc_url} -> net_info alinamadi: {e}")
        return {}

    peers = {}
    try:
        for p in data["result"]["peers"]:
            node_info = p["node_info"]
            net_address = node_info.get("net_address", "")
            if "@" not in net_address or ":" not in net_address:
                continue
            node_id, addr = net_address.split("@", 1)
            ip, port = addr.rsplit(":", 1)
            peers[node_id] = {
                "ip": ip,
                "port": int(port),
                "moniker": node_info.get("moniker", ""),
                "is_outbound": p.get("is_outbound", False),
                "advertised_rpc": node_info.get("other", {}).get("rpc_address", ""),
            }
    except Exception as e:
        print(f"[warn] {rpc_url} -> net_info parse hatasi: {e}")

    return peers


def tcp_probe(ip: str, port: int) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=TCP_TIMEOUT):
            return True
    except Exception:
        return False


def load_history():
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_json(path: Path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def main():
    run_time = datetime.now(timezone.utc).isoformat()
    print(f"[{run_time}] check_peers-lite calisiyor...")

    all_peers = {}
    seen_by = {}

    for rpc in RPC_SOURCES:
        peers = fetch_net_info(rpc)
        print(f"  {rpc} -> {len(peers)} peer bildirdi")
        for node_id, info in peers.items():
            all_peers[node_id] = info
            seen_by.setdefault(node_id, set()).add(rpc)

    print(f"  toplam benzersiz peer: {len(all_peers)}")

    history = load_history()
    results = {}

    for node_id, info in all_peers.items():
        reachable = tcp_probe(info["ip"], info["port"])

        hist = history.get(node_id, [])
        hist.append(1 if reachable else 0)
        hist = hist[-HISTORY_WINDOW:]
        history[node_id] = hist

        uptime_pct = sum(hist) / len(hist) if hist else 0.0

        results[node_id] = {
            "ip": info["ip"],
            "port": info["port"],
            "moniker": info.get("moniker", ""),
            "is_outbound": info.get("is_outbound", False),
            "advertised_rpc": info.get("advertised_rpc", ""),
            "reachable_now": reachable,
            "uptime_pct": round(uptime_pct, 3),
            "measurements": len(hist),
            "seen_by": sorted(seen_by.get(node_id, [])),
            "source_diversity": len(seen_by.get(node_id, [])),
            "reliable": uptime_pct >= UPTIME_THRESHOLD,
        }

    save_json(HISTORY_FILE, history)

    output = {
        "generated_at": run_time,
        "rpc_sources": RPC_SOURCES,
        "total_peers": len(results),
        "reliable_peers": sum(1 for r in results.values() if r["reliable"]),
        "peers": results,
    }
    save_json(OUTPUT_FILE, output)

    print(f"  {output['reliable_peers']}/{output['total_peers']} peer 'reliable' esigini geciyor")
    print(f"  yazildi -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
