import subprocess   # allows us to run commands in the terminal
import json
import csv
import re           # search for patterns in text
import time
import sys
from datetime import datetime

#----------------------RADIO LINK PERFORMANCE MEASUREMENTS---------------------------

OUTPUT_FILE_CSV="performance_metrics.csv"
OUTPUT_FILE_JSON="performance_metrics.json"
BASE_IP="10.0.0.1"	    # TUN IP for the base station
DURATION=30	            # seconds per iperf3 test

# Rates in bps
RATES_BPS = [5000, 10000, 20000, 35000, 50000, 75000, 100000, 125000, 150000, 175000, 200000, 225000, 250000, 275000, 300000]

# added better error handling
def check_server():
    print(f"Checking iperf3 server on {BASE_IP}...")
    try:
        result = subprocess.run(
            ["iperf3", "-c", BASE_IP, "-u", "-b", "5000", "-t", "2", "--json"],
            capture_output=True,
            text=True,
            timeout=10
        )
        data = json.loads(result.stdout)

        if result.returncode != 0 or "end" not in data:
            print("ERROR: iperf3 test failed or server not reachable.")
            print(result.stderr)
            sys.exit(1)

    except subprocess.TimeoutExpired:
        print(f"ERROR: iperf3 server on {BASE_IP} did not respond within 10 seconds.")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"ERROR: iperf3 returned unexpected output. Is iperf3 installed?")
        sys.exit(1)
    except FileNotFoundError:
        print("ERROR: iperf3 is not installed or not found in PATH.")
        sys.exit(1)

    print("Server reachable, starting measurements...")

def run_ping():
    # 0.2 --> 5 samples/second
    return subprocess.Popen(
        ["ping", "-c", str(DURATION), "-i", "0.2", "-q", BASE_IP],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

def run_iperf3(rate_bps):
    result = subprocess.run(
        [
            "iperf3",
            "-c", BASE_IP,
            "-u",
            "-b", str(rate_bps),
            "-t", str(DURATION),
            "--json"
        ],
        capture_output=True,
        text=True
    )
    return json.loads(result.stdout)

def parse_ping_rtt(ping_output):
    # r'...' -> raw string
    # [\d.]+ -> one or more digits or decimal points
    # With () -> save matched value to retrieve later
    match = re.search(r'rtt min/avg/max/mdev = [\d.]+/([\d.]+)/', ping_output)   # extract average RTT from the ping output
    return float(match.group(1)) if match else None

def measure(rate_bps):
    print(f"--- Testing {rate_bps} bps ---")

    # Run ping during iperf3 explicitly (or longer ping window)??
    # Right now ping and iperf3 are not synchronised --> adds noise
    # HOWEVER, timing mismatch is very small
    ping_proc = run_ping()
    iperf_data = run_iperf3(rate_bps)
    ping_output, _ = ping_proc.communicate()

    end = iperf_data.get("end", {})

    recv = (
        end.get("sum_received")
        or end.get("sum")
        or end.get("sum_sent")
    )

    if not recv:
        raise ValueError(f"Bad iperf3 output: {end}")

    # get the measurement we need, return 0 if it does not exist
    output_bps = recv.get("bits_per_second", 0)    # actual measured throughput
    jitter_ms = recv.get("jitter_ms", 0)        # packet timing variation
    loss_pct = recv.get("lost_percent", 0)        # percentage of dropped packets

    rtt_avg = parse_ping_rtt(ping_output)

    print(f"  → out={output_bps:.0f} bps | jitter={jitter_ms:.3f} ms | loss={loss_pct:.1f}% | rtt={rtt_avg} ms")

    return {
        "input_bps": rate_bps,
        "output_bps": round(output_bps, 2),
        "jitter_ms": round(jitter_ms, 3),    # often smaller values -> more precision
        "loss_pct": round(loss_pct, 2),
        "rtt_avg_ms": rtt_avg
    }

# Save to JSON
def save_json(results):
    output = {
        "meta": {
            "base_ip": BASE_IP,
            "duration_s": DURATION,
            "timestamp": datetime.now().isoformat(timespec="seconds")
        },
        "units": {
            "input_bps": "bps",
            "output_bps": "bps",
            "jitter_ms": "ms",
            "loss_pct": "%",
            "rtt_avg_ms": "ms"
        },
        "results": results
    }
    with open(OUTPUT_FILE_JSON, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Results saved to {OUTPUT_FILE_JSON}")

# Save to CSV
def save_csv(results):
    with open(OUTPUT_FILE_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    print(f"Results saved to {OUTPUT_FILE_CSV}")

def main():
    check_server()

    results = []
    for rate in RATES_BPS:
        row = measure(rate)
        results.append(row)
        time.sleep(2)

    save_json(results)
    save_csv(results)
    print("Done.")

if __name__ == "__main__":
    main()

# input_bps --> the rate we (mobile unit) tried to send to the base station
# output_bps --> what the system actually managed to deliver (measured throughput)
# jitter_ms --> how unstable packet timing is under load (latency variation) --> high jitter=congestion
# loss_pct --> how many packets were dropped (packet loss)
# rtt_avg_ms --> ping latency


