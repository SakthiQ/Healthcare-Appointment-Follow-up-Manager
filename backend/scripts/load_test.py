"""Load test: how many signed-in users one server can serve at once.

Simulated patients sign in once, then browse in a loop: the doctor list, a doctor's profile, a
day's free slots, their own appointments and their own account. Each pauses 1-3 seconds
(mean 2 s) between requests, which is faster than a real person, so the result is cautious.
The number of users steps up; a step passes when 95% of responses take under 500 ms and
fewer than 1% fail (any non-2xx answer, including 503 "server busy").

It then measures login throughput (bcrypt makes logins slow on purpose) and, with
--slot-race, has 100 new patients try to hold the same slot at the same instant.

Run it against a local server, never against production: it sends hundreds of requests a
second, and --slot-race creates accounts. It refuses a server that reports
environment "production" in /health.

    cd backend
    # 1. A local server on demo data, rate limits off (one IP plays every user):
    #    DATABASE_URL=sqlite:///./bench.db DEMO_MODE=True RATE_LIMITING_ENABLED=False \\
    #      python -m alembic upgrade head && python -m scripts.seed_demo
    #    (same variables) python -m uvicorn app.main:app --port 8765 --no-access-log
    # 2. In another terminal:
    python -m scripts.load_test --base-url http://127.0.0.1:8765 --slot-race

Measured on 19 Nov 2026 (one process, SQLite, a 22-core machine, default settings):
600 users passed at 266 requests/s with p95 51 ms and no errors; 800 did not (p95 4.6 s,
partly the single-process load generator itself). 35 logins/s. Slot race: 1 hold, 99 refused.
"""
import argparse
import asyncio
import random
import sys
import time
from datetime import date, timedelta

import httpx

DEMO_EMAIL = "patient@demo.example.com"
DEMO_PASSWORD = "demo-password"  # the well-known password scripts/seed_demo.py gives demo accounts
P95_LIMIT_MS = 500
ERROR_LIMIT_PCT = 1.0
THINK_SECONDS = (1.0, 3.0)


def next_weekday() -> str:
    day = date.today() + timedelta(days=7)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.isoformat()


def percentile(values, p):
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(p / 100 * len(ordered))) - 1))
    return ordered[index]


async def browse_step(client, api, token, doctor_id, users, seconds):
    headers = {"Authorization": f"Bearer {token}"}
    day = next_weekday()
    paths = [
        f"{api}/doctors",
        f"{api}/doctors/{doctor_id}",
        f"{api}/doctors/{doctor_id}/slots?date={day}",
        f"{api}/appointments",
        f"{api}/auth/me",
    ]
    latencies, codes = [], {}
    stop_at = time.perf_counter() + seconds

    async def user():
        await asyncio.sleep(random.uniform(0, THINK_SECONDS[1]))  # stagger the start
        i = random.randrange(len(paths))
        while time.perf_counter() < stop_at:
            started = time.perf_counter()
            try:
                code = (await client.get(paths[i % len(paths)], headers=headers)).status_code
            except httpx.HTTPError:
                code = "error"
            latencies.append((time.perf_counter() - started) * 1000)
            codes[code] = codes.get(code, 0) + 1
            i += 1
            await asyncio.sleep(random.uniform(*THINK_SECONDS))

    started = time.perf_counter()
    await asyncio.gather(*(user() for _ in range(users)))
    elapsed = time.perf_counter() - started
    total = len(latencies)
    failed = sum(n for code, n in codes.items() if not (isinstance(code, int) and 200 <= code < 300))
    return {
        "users": users, "rps": total / elapsed, "codes": codes,
        "p50": percentile(latencies, 50), "p95": percentile(latencies, 95), "p99": percentile(latencies, 99),
        "error_pct": 100 * failed / max(total, 1),
    }


async def login_throughput(client, api, email, password, parallel=20, seconds=20):
    ok, failed, latencies = 0, 0, []
    stop_at = time.perf_counter() + seconds

    async def worker():
        nonlocal ok, failed
        while time.perf_counter() < stop_at:
            started = time.perf_counter()
            r = await client.post(f"{api}/auth/login", json={"email": email, "password": password})
            latencies.append((time.perf_counter() - started) * 1000)
            if r.status_code == 200:
                ok += 1
            else:
                failed += 1

    started = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(parallel)))
    return ok / (time.perf_counter() - started), failed, percentile(latencies, 50), percentile(latencies, 95)


async def slot_race(client, api, doctor_id, racers=100):
    stamp = int(time.time())
    password = "load-test-" + str(stamp)
    limit = asyncio.Semaphore(20)

    async def new_patient(i):
        email = f"race{stamp}-{i}@loadtest.example.com"
        async with limit:
            r = await client.post(f"{api}/auth/register",
                                  json={"email": email, "password": password, "full_name": f"Racer {i}"})
            if r.status_code not in (200, 201):
                return None
            r = await client.post(f"{api}/auth/login", json={"email": email, "password": password})
            return r.json().get("access_token") if r.status_code == 200 else None

    tokens = [t for t in await asyncio.gather(*(new_patient(i) for i in range(racers))) if t]
    slots = (await client.get(f"{api}/doctors/{doctor_id}/slots?date={next_weekday()}")).json()["slots"]
    target = [s for s in slots if s["is_available"]][-1]
    gate = asyncio.Event()

    async def race(token):
        await gate.wait()
        r = await client.post(f"{api}/slots/holds", headers={"Authorization": f"Bearer {token}"},
                              json={"doctor_id": doctor_id, "start_time": target["start_time"],
                                    "end_time": target["end_time"]})
        return r.status_code

    tasks = [asyncio.create_task(race(t)) for t in tokens]
    await asyncio.sleep(0.5)  # let every request get ready, then release them together
    gate.set()
    outcome = {}
    for code in await asyncio.gather(*tasks):
        outcome[code] = outcome.get(code, 0) + 1
    return len(tokens), outcome


async def run(args) -> int:
    api = args.base_url.rstrip("/") + "/api/v1"
    limits = httpx.Limits(max_connections=4000, max_keepalive_connections=4000)
    async with httpx.AsyncClient(timeout=30, limits=limits) as client:
        # Fail closed: run only when /health answers and does not say production. The long
        # timeout gives a sleeping free-tier server time to wake up and answer.
        try:
            health = (await client.get(args.base_url.rstrip("/") + "/health", timeout=90)).json()
        except (httpx.HTTPError, ValueError) as exc:
            print(f"Refusing to run: could not read {args.base_url}/health ({type(exc).__name__}).")
            return 2
        if str(health.get("environment", "")).lower() == "production":
            print("Refusing to load-test a server that reports environment=production.")
            return 2
        r = await client.post(f"{api}/auth/login", json={"email": args.email, "password": args.password})
        if r.status_code != 200:
            print(f"Could not sign in as {args.email} ({r.status_code}). Seed demo data first: python -m scripts.seed_demo")
            return 2
        token = r.json()["access_token"]
        doctors = (await client.get(f"{api}/doctors")).json()
        if not doctors:
            print("No doctors to browse. Seed demo data first: python -m scripts.seed_demo")
            return 2
        doctor_id = doctors[0]["id"]

        print(f"{'users':>6} {'req/s':>7} {'p50 ms':>7} {'p95 ms':>7} {'p99 ms':>7} {'errors':>7}  result")
        best = None
        for users in args.steps:
            step = await browse_step(client, api, token, doctor_id, users, args.step_seconds)
            passed = step["p95"] < P95_LIMIT_MS and step["error_pct"] < ERROR_LIMIT_PCT
            best = step if passed else best
            print(f"{users:>6} {step['rps']:>7.0f} {step['p50']:>7.0f} {step['p95']:>7.0f} {step['p99']:>7.0f} "
                  f"{step['error_pct']:>6.1f}%  {'PASS' if passed else 'FAIL'}  {step['codes']}", flush=True)
            if not passed and step["p95"] > 4 * P95_LIMIT_MS:
                break
        if best:
            print(f"\nHighest passing step: {best['users']} concurrent users, {best['rps']:.0f} requests/s, "
                  f"p95 {best['p95']:.0f} ms")

        rate, failed, p50, p95 = await login_throughput(client, api, args.email, args.password)
        print(f"\nLogins: {rate:.1f}/s with 20 parallel clients, p50 {p50:.0f} ms, p95 {p95:.0f} ms, {failed} failed")

        if args.slot_race:
            racers, outcome = await slot_race(client, api, doctor_id)
            print(f"\nSlot race: {racers} patients held the same slot at once -> {outcome} "
                  "(expect one 201 and the rest 409)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8765", help="server to test (not production)")
    parser.add_argument("--email", default=DEMO_EMAIL, help="a patient account to browse as")
    parser.add_argument("--password", default=DEMO_PASSWORD)
    parser.add_argument("--steps", type=int, nargs="+", default=[50, 100, 200, 400, 600, 800, 1000],
                        help="concurrent users for each step")
    parser.add_argument("--step-seconds", type=int, default=30)
    parser.add_argument("--slot-race", action="store_true",
                        help="also race 100 new patients for one slot (creates 100 accounts)")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
