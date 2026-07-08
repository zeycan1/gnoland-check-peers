#!/usr/bin/env python3
"""
infra_diversity.py — gno.land Test13 icin altyapi cesitliligi ozetleyicisi.

check_peers.py'nin zaten topladigi peers.json'daki IP'leri okur, ip-api.com
batch endpoint'i ile hangi barindirma saglayicisina ve ulkeye ait olduklarini
bulur, sonucu SADECE TOPLU ISTATISTIK olarak yazar. Hicbir IP adresi ya da
tekil peer eslesmesi ciktida yer almaz -- amac merkeziyetsizligi olcmek,
kimseyi deşifre etmek degil.

Cikti: infra_diversity.json
  - by_provider: [{provider, count, pct}], en yaygin saglayicidan aza dogru
  - by_country: [{country, count, pct}]
  - hhi_score: Herfindahl-Hirschman Index (0-1), 1'e ne kadar yakinsa
    o kadar merkezilesmis; dusuk skor = saglikli cesitlilik
  - top_provider_pct: en buyuk tek saglayicinin agdaki payi
"""

import json
import subprocess
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

PEERS_FILE = Path(__file__).resolve().parent / "peers.json"
OUTPUT_FILE = Path(__file__).resolve().parent / "infra_diversity.json"
DATA_DIR = Path(__file__).resolve().parent

IPAPI_BATCH_URL = "http://ip-api.com/batch?fields=status,country,isp,org,query"
BATCH_SIZE = 100
HTTP_TIMEOUT = 15


def load_peer_ips():
    if not PEERS_FILE.exists():
        print("[error] peers.json bulunamadi, once check_peers.py calistir")
        return []
    data = json.loads(PEERS_FILE.read_text())
    ips = sorted({p["ip"] for p in data.get("peers", {}).values() if p.get("ip")})
    return ips


def query_batch(ips):
    """ip-api.com'a tek batch istegi atar, {ip: {provider, country}} doner."""
    body = json.dumps(ips).encode()
    req = urllib.request.Request(
        IPAPI_BATCH_URL, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            results = json.loads(resp.read().decode())
    except Exception as e:
        print(f"[warn] ip-api batch basarisiz: {e}")
        return {}

    out = {}
    for r in results:
        if r.get("status") != "success":
            continue
        ip = r.get("query")
        provider = r.get("isp") or r.get("org") or "Bilinmiyor"
        country = r.get("country") or "Bilinmiyor"
        out[ip] = {"provider": provider, "country": country}
    return out


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
    print(f"[{run_time}] infra_diversity calisiyor...")

    ips = load_peer_ips()
    print(f"  {len(ips)} benzersiz IP bulundu")
    if not ips:
        return

    lookups = {}
    for i in range(0, len(ips), BATCH_SIZE):
        chunk = ips[i:i + BATCH_SIZE]
        lookups.update(query_batch(chunk))
        print(f"  {len(lookups)}/{len(ips)} IP cozumlendi")

    provider_counts = {}
    country_counts = {}
    for ip in ips:
        info = lookups.get(ip)
        if not info:
            continue
        provider_counts[info["provider"]] = provider_counts.get(info["provider"], 0) + 1
        country_counts[info["country"]] = country_counts.get(info["country"], 0) + 1

    total = sum(provider_counts.values())
    if total == 0:
        print("[error] hicbir IP cozumlenemedi, cikiliyor")
        return

    by_provider = sorted(
        [{"provider": k, "count": v, "pct": round(v / total, 4)} for k, v in provider_counts.items()],
        key=lambda x: -x["count"]
    )
    by_country = sorted(
        [{"country": k, "count": v, "pct": round(v / total, 4)} for k, v in country_counts.items()],
        key=lambda x: -x["count"]
    )

    hhi = sum((v / total) ** 2 for v in provider_counts.values())
    top_provider_pct = by_provider[0]["pct"] if by_provider else 0

    output = {
        "generated_at": run_time,
        "total_analyzed": total,
        "unique_providers": len(provider_counts),
        "unique_countries": len(country_counts),
        "hhi_score": round(hhi, 4),
        "top_provider_pct": top_provider_pct,
        "by_provider": by_provider,
        "by_country": by_country,
    }
    save_json(OUTPUT_FILE, output)
    print(f"  yazildi -> {OUTPUT_FILE} (HHI: {hhi:.3f}, en buyuk saglayici: %{top_provider_pct*100:.1f})")

    git_push(DATA_DIR, ["infra_diversity.json"], f"infra diversity update: {run_time}")


if __name__ == "__main__":
    main()
