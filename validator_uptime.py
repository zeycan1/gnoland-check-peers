#!/usr/bin/env python3
"""
validator_uptime.py — gno.land Test13 icin validator uptime / missed-block takipcisi.

Not: validator (consensus) adresi ile P2P node ID FARKLI anahtarlardir,
bu yuzden su an moniker eslestirmesi yok. Sadece validator adresiyle takip eder.

Mantik:
1) Son taranan blok yuksekligini state dosyasindan okur (ilk calistirmada geriye ~100 blok gider)
2) O yukseklikten simdiki en son bloga kadar (guvenlik siniri ile) her blogun precommit'lerini ceker
3) Her aktif validator icin imzaladi/kacirdi sayar, kacirma serisini takip eder
4) Sonucu validators.json'a yazar, git'e otomatik push eder
"""

import json
import subprocess
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

PRIMARY_RPC = "http://127.0.0.1:54657"          # kendi node'un, hizli
FALLBACK_RPC = "https://rpc.test13.testnets.gno.land"

HTTP_TIMEOUT = 5
MAX_BLOCKS_PER_RUN = 800   # bir calistirmada en fazla bu kadar blok tara
BACKFILL_ON_FIRST_RUN = 100

DATA_DIR = Path(__file__).resolve().parent
STATE_FILE = DATA_DIR / "validator_state.json"
OUTPUT_FILE = DATA_DIR / "validators.json"


def rpc_get(path: str):
    for base in (PRIMARY_RPC, FALLBACK_RPC):
        url = base.rstrip("/") + path
        try:
            with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            print(f"[warn] {url} basarisiz: {e}")
    return None


def get_latest_height():
    data = rpc_get("/status")
    if not data:
        return None
    return int(data["result"]["sync_info"]["latest_block_height"])


def get_active_validators():
    data = rpc_get("/validators")
    if not data:
        return {}
    out = {}
    for v in data["result"]["validators"]:
        out[v["address"]] = {"voting_power": int(v["voting_power"])}
    return out


def get_block_signers(height: int):
    """O yukseklikteki bloğu imzalayan validator adreslerinin set'ini doner."""
    data = rpc_get(f"/block?height={height}")
    if not data:
        return None
    try:
        precommits = data["result"]["block"]["last_commit"]["precommits"]
    except Exception:
        return None
    signed = set()
    for p in precommits:
        if p and p.get("signature"):
            signed.add(p["validator_address"])
    return signed


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_scanned_height": 0, "validators": {}}


def save_json(path: Path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def git_push(data_dir: Path, files: list, message: str):
    def run(cmd):
        return subprocess.run(cmd, cwd=data_dir, capture_output=True, text=True)

    run(["git", "add"] + files)
    diff = run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        print("  degisiklik yok, commit atlanildi")
        return
    commit = run(["git", "commit", "-m", message])
    if commit.returncode != 0:
        print(f"[warn] git commit basarisiz: {commit.stderr.strip()}")
        return
    push = run(["git", "push"])
    if push.returncode != 0:
        print(f"[warn] git push basarisiz: {push.stderr.strip()}")
    else:
        print("  git push basarili")


def main():
    run_time = datetime.now(timezone.utc).isoformat()
    print(f"[{run_time}] validator_uptime calisiyor...")

    latest = get_latest_height()
    if latest is None:
        print("[error] en son blok yuksekligi alinamadi, cikiliyor")
        return

    active = get_active_validators()
    print(f"  aktif validator sayisi: {len(active)}")

    state = load_state()
    last_scanned = state.get("last_scanned_height", 0)

    if last_scanned == 0:
        start = max(1, latest - BACKFILL_ON_FIRST_RUN)
    else:
        start = last_scanned + 1

    end = min(latest, start + MAX_BLOCKS_PER_RUN - 1)

    if start > end:
        print("  yeni blok yok, atlaniliyor")
        return

    print(f"  taraniyor: blok {start} -> {end} ({end - start + 1} blok)")

    vstats = state.get("validators", {})
    for addr in active:
        vstats.setdefault(addr, {
            "signed": 0, "missed": 0, "cur_streak": 0, "max_streak": 0
        })

    scanned = 0
    for h in range(start, end + 1):
        signers = get_block_signers(h)
        if signers is None:
            print(f"  [warn] blok {h} alinamadi, atlaniyor")
            continue
        for addr in active:
            st = vstats[addr]
            if addr in signers:
                st["signed"] += 1
                st["cur_streak"] = 0
            else:
                st["missed"] += 1
                st["cur_streak"] += 1
                st["max_streak"] = max(st["max_streak"], st["cur_streak"])
        scanned += 1

    print(f"  {scanned} blok tarandi")

    state["last_scanned_height"] = end
    state["validators"] = vstats
    save_json(STATE_FILE, state)

    results = {}
    for addr, st in vstats.items():
        total = st["signed"] + st["missed"]
        uptime_pct = (st["signed"] / total) if total else 1.0
        results[addr] = {
            "voting_power": active.get(addr, {}).get("voting_power", 0),
            "signed": st["signed"],
            "missed": st["missed"],
            "total_observed": total,
            "uptime_pct": round(uptime_pct, 4),
            "current_missed_streak": st["cur_streak"],
            "max_missed_streak": st["max_streak"],
        }

    output = {
        "generated_at": run_time,
        "last_scanned_height": end,
        "total_validators": len(results),
        "results": results,
    }
    save_json(OUTPUT_FILE, output)
    print(f"  yazildi -> {OUTPUT_FILE}")

    git_push(DATA_DIR, ["validators.json", "validator_state.json"],
             f"validator uptime update: {run_time}")


if __name__ == "__main__":
    main()
