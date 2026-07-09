# Stress / Load Tests — "swarming" the server

Stress testing answers the lecture's question: *how does the server behave with
500 users? 1000 users? all hitting a heavy feature at once?* We use two of the
tools the lecture names — **Locust** (a swarm of scripted users) and **Apache
Bench** (a raw request flood) — plus an in-process concurrency test.

## 1. Locust — a swarm of realistic users (primary)

[`locustfile.py`](./locustfile.py) spins up virtual users that register, log
in and then loop over real actions (open tickets, list tickets, browse forums;
agents poll the queue). Locust reports **requests/sec, latency percentiles and
error rate** live.

```bash
# Lift the per-IP rate limit first, or you'll just measure the limiter:
#   set RATE_LIMIT_REQUESTS=1000000 in .env, then:
docker compose up --build -d

pip install -r tests/Stress_Tests/requirements.txt

# Web UI (open http://localhost:8089 and set users + spawn rate):
locust -f tests/Stress_Tests/locustfile.py --host http://localhost:8080

# Headless: 200 users, 20/s ramp, 1 minute, CSV report:
locust -f tests/Stress_Tests/locustfile.py --host http://localhost:8080 \
       --headless -u 200 -r 20 -t 1m --csv results
```

> **Rate limiter caveat.** The gateway throttles each client IP to
> `RATE_LIMIT_REQUESTS` per window (default 30/60s). A single load generator
> shares one IP across all virtual users, so leave the limit lifted for a
> meaningful load test.

## 2. Apache Bench — quick raw flood

Good for a fast first number on a single endpoint (avg latency, req/s, error
rate). `-n` total requests, `-c` concurrency:

```bash
# 2000 requests, 100 concurrent, against the health endpoint:
ab -n 2000 -c 100 http://localhost:8080/health

# POST load (register) with a JSON body:
ab -n 500 -c 50 -p body.json -T application/json \
   http://localhost:8080/api/auth/register
```

## 3. Concurrency / race-condition test (in-process)

The queue's race-safe `claim_next` is proven by
`api-service/tests/test_queue_api.py::test_concurrent_claims_never_double_assign`
— 8 agents claim concurrently and no ticket is ever double-assigned. Run it
with the api-service suite (no external tool, no stack):

```bash
cd api-service && pytest tests/test_queue_api.py -k concurrent
```
