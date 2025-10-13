#!/usr/bin/env python3
# dns_uptimer_ai.py
import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal
import socket
import statistics
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

import dns.resolver
import aiohttp
from aiohttp import web

# Optional uvloop for performance (skips on Windows if not installed)
with contextlib.suppress(Exception):
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

LOG = logging.getLogger("dns_uptimer_ai")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

@dataclass
class LatencyStats:
    samples: deque = field(default_factory=lambda: deque(maxlen=200))
    ema: Optional[float] = None
    alpha: float = 0.25  # EMA smoothing
    last_anomaly: Optional[str] = None
    last_anomaly_ts: Optional[float] = None

    def add(self, value: float):
        self.samples.append(value)
        if self.ema is None:
            self.ema = value
        else:
            self.ema = self.alpha * value + (1 - self.alpha) * self.ema

    def zscore(self, value: float) -> float:
        if len(self.samples) < 10:
            return 0.0
        mu = statistics.mean(self.samples)
        try:
            sigma = statistics.pstdev(self.samples)
        except statistics.StatisticsError:
            sigma = 0.0
        if sigma == 0:
            return 0.0
        return (value - mu) / sigma

    def summary(self) -> Dict:
        if len(self.samples) == 0:
            return {"count": 0}
        median = statistics.median(self.samples)
        p95 = sorted(self.samples)[int(0.95 * (len(self.samples) - 1))]
        return {
            "count": len(self.samples),
            "median_ms": round(median, 2),
            "p95_ms": round(p95, 2),
            "ema_ms": round(self.ema or median, 2)
        }

@dataclass
class UptimeStats:
    window: int = 200
    results: deque = field(default_factory=lambda: deque(maxlen=200))

    def add(self, success: bool):
        self.results.append(1 if success else 0)

    def ratio(self) -> float:
        if not self.results:
            return 0.0
        return sum(self.results) / len(self.results)

class DNSUptimerAI:
    def __init__(self,
                 targets: List[str],
                 resolvers: List[str],
                 records: List[str],
                 interval: float,
                 window: int,
                 timeout: float = 3.0,
                 webhook: Optional[str] = None):
        self.targets = targets
        self.resolvers = resolvers
        self.records = records
        self.interval = interval
        self.window = window
        self.timeout = timeout
        self.webhook = webhook

        self.latency: Dict[Tuple[str, str, str], LatencyStats] = defaultdict(lambda: LatencyStats())
        self.uptime: Dict[Tuple[str, str, str], UptimeStats] = defaultdict(lambda: UptimeStats(window=window))
        self.last_results: Dict[Tuple[str, str, str], Dict] = {}
        self._stop = asyncio.Event()

    async def _alert(self, text: str, payload: Dict):
        LOG.warning(text)
        if not self.webhook:
            return
        with contextlib.suppress(Exception):
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                await session.post(self.webhook, json={"text": text, "payload": payload})

    async def _resolve_once(self, target: str, resolver_ip: str, rtype: str) -> Tuple[bool, float, Optional[List[str]], Optional[str]]:
        start = time.perf_counter()
        try:
            res = dns.resolver.Resolver()
            res.nameservers = [resolver_ip]
            res.timeout = self.timeout
            res.lifetime = self.timeout
            ans = res.resolve(target, rtype)
            latency_ms = (time.perf_counter() - start) * 1000.0
            addrs = [str(r) for r in ans]
            return True, latency_ms, addrs, None
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return False, latency_ms, None, str(e)

    async def _check_and_analyze(self, target: str, resolver_ip: str, rtype: str):
        key = (target, resolver_ip, rtype)
        ok, latency_ms, addrs, err = await self._resolve_once(target, resolver_ip, rtype)

        self.uptime[key].add(ok)
        self.latency[key].add(latency_ms)

        z = self.latency[key].zscore(latency_ms)
        summary = self.latency[key].summary()
        upt = self.uptime[key].ratio()
        result = {
            "target": target,
            "resolver": resolver_ip,
            "rtype": rtype,
            "ok": ok,
            "latency_ms": round(latency_ms, 2),
            "zscore": round(z, 2),
            "addresses": addrs or [],
            "error": err,
            "uptime_window_ratio": round(upt, 4),
            "latency_summary": summary,
            "timestamp": time.time()
        }
        self.last_results[key] = result

        # AI-ish anomaly logic
        anomaly = None
        if not ok:
            if upt < 0.95 and len(self.uptime[key].results) >= 20:
                anomaly = f"Repeated failures: uptime {upt:.2%}"
            else:
                anomaly = "Single failure"
        elif z >= 3.0 and latency_ms > (self.latency[key].ema or latency_ms) * 1.5:
            anomaly = f"Latency spike: z={z:.2f}, {latency_ms:.1f} ms"

        if anomaly:
            self.latency[key].last_anomaly = anomaly
            self.latency[key].last_anomaly_ts = time.time()
            await self._alert(
                f"[DNS] {target} via {resolver_ip} ({rtype}) anomaly: {anomaly}",
                result
            )

        LOG.info(f"{target} | {resolver_ip} | {rtype} | ok={ok} | {latency_ms:.1f} ms | upt={upt:.2%} | z={z:.2f}")

    async def run_loop(self):
        while not self._stop.is_set():
            tasks = []
            for t in self.targets:
                for r in self.resolvers:
                    for rt in self.records:
                        tasks.append(self._check_and_analyze(t, r, rt))
            # Execute checks concurrently
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    def stop(self):
        self._stop.set()

    def snapshot(self) -> Dict:
        # Structure the latest state for the dashboard
        out = defaultdict(list)
        for (target, resolver, rtype), result in self.last_results.items():
            lat = self.latency[(target, resolver, rtype)]
            out[target].append({
                "resolver": resolver,
                "rtype": rtype,
                **result,
                "last_anomaly": lat.last_anomaly,
                "last_anomaly_ts": lat.last_anomaly_ts
            })
        return {"targets": out, "generated_at": time.time()}

# --- Web dashboard ---
def make_app(monitor: DNSUptimerAI) -> web.Application:
    app = web.Application()

    async def json_status(request):
        return web.json_response(monitor.snapshot())

    async def html_status(request):
        snap = monitor.snapshot()
        # Minimal HTML for quick glance
        rows = []
        for target, entries in snap["targets"].items():
            for e in entries:
                color = "#26a269" if e["ok"] else "#c01c28"
                rows.append(f"""
<tr>
  <td>{target}</td>
  <td>{e['resolver']}</td>
  <td>{e['rtype']}</td>
  <td style="color:{color};font-weight:600">{'OK' if e['ok'] else 'FAIL'}</td>
  <td>{e['latency_ms']} ms</td>
  <td>{e['uptime_window_ratio']*100:.2f}%</td>
  <td>{e['latency_summary'].get('median_ms','-')} / {e['latency_summary'].get('p95_ms','-')} / {e['latency_summary'].get('ema_ms','-')} ms</td>
  <td>{e.get('last_anomaly','')}</td>
</tr>
""")
        html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>AI DNS Uptime</title>
<style>
body {{ font-family: system-ui, Segoe UI, sans-serif; margin: 24px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: 8px; font-size: 14px; }}
th {{ background: #f4f4f4; text-align: left; }}
caption {{ text-align:left; font-weight:700; margin-bottom:8px; }}
</style>
</head>
<body>
<caption>AI DNS Uptime Checker</caption>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
<table>
<thead><tr>
<th>Target</th><th>Resolver</th><th>Type</th><th>Status</th><th>Latency</th><th>Uptime</th><th>Median/P95/EMA</th><th>Anomaly</th>
</tr></thead>
<tbody>
{''.join(rows) or '<tr><td colspan="8">No data yet...</td></tr>'}
</tbody>
</table>
<p>JSON API: <a href="/api/status">/api/status</a></p>
</body>
</html>
"""
        return web.Response(text=html, content_type="text/html")

    app.add_routes([
        web.get("/api/status", json_status),
        web.get("/", html_status)
    ])
    return app

# --- CLI ---
def parse_args():
    parser = argparse.ArgumentParser(description="AI DNS Uptime Checker")
    parser.add_argument("--targets", type=str, required=True, help="Comma-separated domains")
    parser.add_argument("--resolvers", type=str, default="1.1.1.1,8.8.8.8", help="Comma-separated DNS servers")
    parser.add_argument("--records", type=str, default="A,AAAA", help="Comma-separated DNS record types")
    parser.add_argument("--interval", type=float, default=15.0, help="Seconds between checks")
    parser.add_argument("--window", type=int, default=200, help="Rolling window size")
    parser.add_argument("--timeout", type=float, default=3.0, help="DNS query timeout seconds")
    parser.add_argument("--webhook", type=str, default=None, help="Optional alert webhook URL")
    parser.add_argument("--port", type=int, default=8080, help="Web dashboard port")
    return parser.parse_args()

async def main_async(args):
    targets = [t.strip() for t in args.targets.split(",") if t.strip()]
    resolvers = [r.strip() for r in args.resolvers.split(",") if r.strip()]
    records = [rt.strip().upper() for rt in args.records.split(",") if rt.strip()]
    monitor = DNSUptimerAI(
        targets=targets,
        resolvers=resolvers,
        records=records,
        interval=args.interval,
        window=args.window,
        timeout=args.timeout,
        webhook=args.webhook
    )

    # graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, monitor.stop)

    runner_task = asyncio.create_task(monitor.run_loop())

    app = make_app(monitor)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", args.port)
    await site.start()
    LOG.info(f"Dashboard http://localhost:{args.port} | API /api/status")

    await monitor._stop.wait()
    runner_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await runner_task
    await runner.cleanup()

def main():
    args = parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
