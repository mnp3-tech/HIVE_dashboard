"""Local OS resources + model-limit normalisation (P1.1). Stdlib only.

Honesty rules: a value exists only if the OS (or provider) returned it and it passes
validation; otherwise it is UNKNOWN with a reason. Nothing is estimated, clamped into
range, or filled from a default. MTP/PTP phones are never treated as disks.

The Windows probe is an ADAPTER BOUNDARY: `collect_system(runner=...)` takes an injectable
runner, tests use mocked output. The real PowerShell/nvidia-smi calls are NOT VERIFIED in
the Linux cloud container (no PowerShell here) and must be verified on the Windows PC.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import threading
import time
from datetime import datetime, timezone

PROBE_TIMEOUT_S = 8
MAX_OUTPUT_CHARS = 200_000
CACHE_TTL_S = 5.0

# Fixed script: no request-derived text is ever interpolated into it.
POWERSHELL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$r = [ordered]@{ errors = [ordered]@{} }
try { $r.cpu_percent = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average } catch { $r.errors.cpu = $_.Exception.Message }
try { $o = Get-CimInstance Win32_OperatingSystem; $r.mem_total_kb = [int64]$o.TotalVisibleMemorySize; $r.mem_free_kb = [int64]$o.FreePhysicalMemory } catch { $r.errors.memory = $_.Exception.Message }
try { $r.gpus = @(Get-CimInstance Win32_VideoController | ForEach-Object { [string]$_.Name }) } catch { $r.errors.gpu = $_.Exception.Message }
try {
  $d = @{}; Get-Disk | ForEach-Object { $d[[string]$_.Number] = @{ bus = [string]$_.BusType; readonly = [bool]$_.IsReadOnly } }
  $r.volumes = @(Get-Volume | Where-Object { $_.DriveLetter } | ForEach-Object {
    $p = Get-Partition -DriveLetter $_.DriveLetter -ErrorAction SilentlyContinue
    $n = if ($p) { [string]$p.DiskNumber } else { $null }
    [ordered]@{ letter = [string]$_.DriveLetter; label = [string]$_.FileSystemLabel; drive_type = [string]$_.DriveType; size = [int64]$_.Size; free = [int64]$_.SizeRemaining
                bus = if ($n -and $d.ContainsKey($n)) { $d[$n].bus } else { $null }; readonly = if ($n -and $d.ContainsKey($n)) { $d[$n].readonly } else { $null } } })
} catch { $r.errors.disks = $_.Exception.Message }
try { $r.pnp = @(Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'USB\VID_*' -or $_.Class -eq 'WPD' } | Select-Object -First 40 | ForEach-Object { [ordered]@{ name = [string]$_.FriendlyName; class = [string]$_.Class; status = [string]$_.Status } }) } catch { $r.errors.usb = $_.Exception.Message }
try { $r.temp_deci_kelvin = @(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature | ForEach-Object { [double]$_.CurrentTemperature }) } catch { $r.errors.temperature = $_.Exception.Message }
$r | ConvertTo-Json -Compress -Depth 5
"""
POWERSHELL_ARGV = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", POWERSHELL_SCRIPT]
NVIDIA_ARGV = ["nvidia-smi", "--query-gpu=name,utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rec(value=None, unit=None, validity="unknown", source=None, reason=None, observed_at=None, **extra):
    out = {"value": value, "unit": unit, "validity": validity, "source": source, "observed_at": observed_at, "reason": reason}
    out.update(extra)
    return out


def _unknown(source, reason, unit=None, **extra):
    return _rec(None, unit, "unavailable", source, reason, None, **extra)


def _num(v):
    """A finite real number or None. Booleans and NaN/inf are rejected."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def default_runner(argv, timeout=PROBE_TIMEOUT_S):
    """Run one FIXED argv with shell=False; returns (returncode, stdout). Raises OSError/TimeoutExpired."""
    p = subprocess.run(argv, shell=False, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "")[:MAX_OUTPUT_CHARS]


def _classify_volume(v):
    bus = str(v.get("bus") or "").upper()
    dtype = str(v.get("drive_type") or "").lower()
    if dtype == "removable":  # flash/SD media: the OS says so explicitly, even over a USB bus
        return "removable"
    if bus == "USB":
        return "external"
    if dtype in ("cd-rom", "cdrom", "ram disk", "network"):
        return dtype
    return "fixed"


def _parse_disks(raw, src, observed):
    disks, bad = [], 0
    for v in (raw.get("volumes") or []) if isinstance(raw.get("volumes"), list) else []:
        if not isinstance(v, dict) or not str(v.get("letter") or "").strip():
            bad += 1
            continue
        size, free = _num(v.get("size")), _num(v.get("free"))
        letter = str(v["letter"]).strip()[:1].upper()
        kind = _classify_volume(v)
        ok = size is not None and free is not None and size > 0 and 0 <= free <= size
        ro = v.get("readonly")
        disks.append({
            "id": f"{letter}:\\", "label": str(v.get("label") or "")[:60] or None, "kind": kind,
            "total_bytes": int(size) if ok else None, "free_bytes": int(free) if ok else None,
            "access": ("Read-only" if ro is True else "Read/Write" if ro is False else None),
            "validity": "valid" if ok else "unavailable",
            "reason": None if ok else "OS returned an invalid or missing size/free space",
            "source": src, "observed_at": observed,
        })
        if not ok:
            bad += 1
    return disks[:26]


_MTP_CLASSES = {"WPD", "PORTABLEDEVICE", "IMAGE"}


def _parse_usb(raw, src, observed):
    out = []
    for d in (raw.get("pnp") or []) if isinstance(raw.get("pnp"), list) else []:
        if not isinstance(d, dict):
            continue
        name = str(d.get("name") or "").strip()[:80]
        cls = str(d.get("class") or "").strip()
        if not name:
            continue
        low = name.lower()
        if "root hub" in low or "generic usb hub" in low or "composite device" in low:
            continue  # plumbing, not a user device
        if cls.upper() in _MTP_CLASSES:
            out.append({"name": name, "kind": "phone_mtp_ptp", "status": "Connected" if str(d.get("status")).upper() == "OK" else (str(d.get("status") or "UNKNOWN")[:20]),
                        "protocol": "MTP/PTP", "storage_metrics": "unavailable", "storage_note": "Storage metrics unavailable",
                        "source": src, "observed_at": observed})
        else:
            out.append({"name": name, "kind": "usb_device", "status": "Connected" if str(d.get("status")).upper() == "OK" else (str(d.get("status") or "UNKNOWN")[:20]),
                        "protocol": None, "storage_metrics": "not_applicable", "storage_note": None, "source": src, "observed_at": observed})
    return out[:40]


def parse_powershell(raw, now=None):
    """Validate the PowerShell JSON object into the dashboard contract. Pure function."""
    observed = now or _now()
    src = "windows:powershell"
    errs = raw.get("errors") if isinstance(raw.get("errors"), dict) else {}
    cpu_v = _num(raw.get("cpu_percent"))
    if cpu_v is not None and 0 <= cpu_v <= 100:
        cpu = _rec(round(cpu_v, 1), "%", "valid", f"{src}/Win32_Processor", None, observed)
    else:
        cpu = _unknown(f"{src}/Win32_Processor", str(errs.get("cpu") or "CPU load not returned or out of range")[:160], "%")
    tot, fr = _num(raw.get("mem_total_kb")), _num(raw.get("mem_free_kb"))
    if tot and tot > 0 and fr is not None and 0 <= fr <= tot:
        used = tot - fr
        memory = _rec(round(used / tot * 100, 1), "%", "valid", f"{src}/Win32_OperatingSystem", None, observed, used_bytes=int(used * 1024), total_bytes=int(tot * 1024))
    else:
        memory = _unknown(f"{src}/Win32_OperatingSystem", str(errs.get("memory") or "Memory totals not returned or inconsistent")[:160], "%")
    disks = _parse_disks(raw, src, observed)
    system_letter = (os.environ.get("SystemDrive") or "C:")[:1].upper()
    sysd = next((d for d in disks if d["id"][0] == system_letter and d["validity"] == "valid"), None)
    if sysd:
        disk = _rec(round((1 - sysd["free_bytes"] / sysd["total_bytes"]) * 100, 1), "%", "valid", f"{src}/Get-Volume", None, observed,
                    drive=sysd["id"], free_bytes=sysd["free_bytes"], total_bytes=sysd["total_bytes"])
    else:
        disk = _unknown(f"{src}/Get-Volume", str(errs.get("disks") or "System drive not reported or invalid")[:160], "%")
    gpus = [str(g)[:80] for g in raw.get("gpus", []) if isinstance(g, str) and g.strip()] if isinstance(raw.get("gpus"), list) else []
    gpu = _unknown(f"{src}/Win32_VideoController", "GPU utilization is not provided by the OS counters used here" + ("" if not errs.get("gpu") else f"; {str(errs['gpu'])[:100]}"), "%", adapters=gpus)
    temps = raw.get("temp_deci_kelvin")
    tvals = [(_num(t) / 10.0 - 273.15) for t in temps if _num(t) is not None] if isinstance(temps, list) else []
    tvals = [t for t in tvals if -40 <= t <= 150]
    if tvals:
        temperature = _rec(round(max(tvals), 1), "C", "valid", f"{src}/MSAcpi_ThermalZoneTemperature", "ACPI thermal zone; not necessarily the CPU die", observed)
    else:
        temperature = _unknown(f"{src}/MSAcpi_ThermalZoneTemperature", str(errs.get("temperature") or "No valid temperature returned (often needs elevation or vendor tool)")[:160], "C")
    return {"cpu": cpu, "memory": memory, "disk": disk, "gpu": gpu, "temperature": temperature, "disks": disks, "usb": _parse_usb(raw, src, observed),
            # An empty list only means "none" if the probe actually returned a list; otherwise it is UNKNOWN.
            "disks_known": isinstance(raw.get("volumes"), list), "usb_known": isinstance(raw.get("pnp"), list)}


def apply_nvidia(result, output, now=None):
    """Fill GPU utilization/temperature ONLY from a well-formed nvidia-smi line. Mutates and returns result."""
    observed = now or _now()
    line = (output or "").strip().splitlines()[0] if (output or "").strip() else ""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) == 3:
        try:
            util, temp = float(parts[1]), float(parts[2])
        except ValueError:
            return result
        if math.isfinite(util) and 0 <= util <= 100:
            result["gpu"] = _rec(round(util, 1), "%", "valid", "nvidia-smi", None, observed, adapters=[parts[0][:80]])
        if math.isfinite(temp) and 0 <= temp <= 150 and result["temperature"]["validity"] != "valid":
            result["temperature"] = _rec(round(temp, 1), "C", "valid", "nvidia-smi", "GPU temperature", observed)
    return result


def unavailable_result(reason, source="local:os-probe"):
    u = lambda unit: _unknown(source, reason, unit)
    return {"cpu": u("%"), "memory": u("%"), "disk": u("%"), "gpu": u("%"), "temperature": u("C"), "disks": [], "usb": [], "disks_known": False, "usb_known": False}


def collect_system(runner=None, platform_name=None, now=None):
    """Return {items, evidence}. Never raises; any failure becomes per-field UNKNOWN with a reason."""
    plat = platform_name or os.name
    observed = now or _now()
    if plat != "nt":
        items = unavailable_result("OS probe is implemented for Windows (PowerShell) only; NOT VERIFIED on this platform")
        return {"items": items, "evidence": {"source": "local:os-probe", "validity": "unavailable", "observed_at": observed, "reason": "Non-Windows host: no OS metrics are reported"}}
    run = runner or default_runner
    try:
        code, out = run(POWERSHELL_ARGV)
    except subprocess.TimeoutExpired:
        return {"items": unavailable_result("OS probe timed out"), "evidence": {"source": "windows:powershell", "validity": "unavailable", "observed_at": observed, "reason": "PowerShell probe timed out"}}
    except (OSError, ValueError) as e:
        return {"items": unavailable_result("PowerShell not runnable: " + str(e)[:100]), "evidence": {"source": "windows:powershell", "validity": "unavailable", "observed_at": observed, "reason": "PowerShell not runnable"}}
    try:
        raw = json.loads(out)
        if not isinstance(raw, dict) or code != 0:
            raise ValueError("unexpected output")
    except ValueError:
        return {"items": unavailable_result("OS probe returned unusable output"), "evidence": {"source": "windows:powershell", "validity": "unavailable", "observed_at": observed, "reason": f"PowerShell exit {code}; output was not valid JSON"}}
    items = parse_powershell(raw, observed)
    try:  # optional vendor tool; absence is normal and silent
        c2, o2 = run(NVIDIA_ARGV)
        if c2 == 0:
            apply_nvidia(items, o2, observed)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    valids = [items[k]["validity"] == "valid" for k in ("cpu", "memory", "disk")]
    validity = "valid" if all(valids) else "degraded" if any(valids) else "unavailable"
    return {"items": items, "evidence": {"source": "windows:powershell", "validity": validity, "observed_at": observed, "reason": None if validity == "valid" else "Some OS values were not returned; see per-field reasons"}}


_cache = {"at": 0.0, "value": None}
_lock = threading.Lock()


def cached_system(runner=None, platform_name=None, clock=time.monotonic):
    with _lock:
        if _cache["value"] is not None and clock() - _cache["at"] < CACHE_TTL_S:
            return _cache["value"]
        value = collect_system(runner, platform_name)
        _cache.update(at=clock(), value=value)
        return value


# ---------------------------------------------------------------- model limits
PROVIDERS = (("gpt", "GPT"), ("claude", "CLAUDE"), ("codex", "CODEX"), ("local", "LOCAL"))
LIMIT_STATUSES = ("KNOWN", "UNKNOWN", "NOT_PROVIDED", "ESTIMATED")


def limit_record(provider_key, label, worker):
    """worker: the registry record for this provider, or None. Statuses:
    UNKNOWN       no record from any source for this provider;
    NOT_PROVIDED  a record exists but carries no usable limit object;
    KNOWN         limits.basis == 'provider' with a finite numeric limit (and optional available);
    ESTIMATED     limits.basis == 'estimate' (shown as an estimate, never as known)."""
    base = {"provider": provider_key, "label": label, "status": "UNKNOWN", "limit": None, "available": None, "unit": None, "model": None, "reason": "No worker record observed for this provider"}
    if not isinstance(worker, dict):
        return base
    base["model"] = str(worker.get("model"))[:60] if worker.get("model") else None
    lim = worker.get("limits") if isinstance(worker.get("limits"), dict) else None
    if not lim:
        base.update(status="NOT_PROVIDED", reason="Worker record exists but returned no limits")
        return base
    limit, avail = _num(lim.get("limit")), _num(lim.get("available"))
    basis = str(lim.get("basis") or "").lower()
    if limit is None or limit < 0 or (avail is not None and (avail < 0 or avail > limit)) or basis not in ("provider", "estimate"):
        base.update(status="NOT_PROVIDED", reason="Limits object was malformed or had no recognised basis")
        return base
    base.update(status="KNOWN" if basis == "provider" else "ESTIMATED", limit=limit, available=avail, unit=str(lim.get("unit") or "tokens")[:12],
                reason="Provider-returned limit" if basis == "provider" else "Estimate, not provider-confirmed")
    return base


def model_limits(workers):
    """Always four rows (GPT, CLAUDE, CODEX, LOCAL) so no provider is privileged or hidden."""
    items = []
    for key, label in PROVIDERS:
        hit = None
        for w in workers or []:
            if not isinstance(w, dict):
                continue
            hay = " ".join(str(w.get(k) or "") for k in ("provider", "name", "id")).lower()
            if (key == "local" and any(t in hay for t in ("local", "lmstudio", "lm-studio", "ollama"))) or (key != "local" and key in hay):
                hit = w
                break
        items.append(limit_record(key, label, hit))
    return items
