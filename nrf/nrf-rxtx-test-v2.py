#!/usr/bin/env python3
"""
NRF24L01+ TX/RX throughput test.

Sends --count packets of --size bytes from Radio 1 (SPI1) to Radio 0 (SPI0)
on a configurable RF channel, then reports throughput and packet loss.

TX and RX run concurrently in two threads so the radios operate simultaneously,
matching the architecture students will use in the project.

Install the library once:
    pip3 install pyrf24

Usage examples:
    python3 nrf-rxtx-test.py                          # defaults
    python3 nrf-rxtx-test.py --count 200 --size 32
    python3 nrf-rxtx-test.py --channel 100 --count 500

Hardware connections (Raspberry Pi GPIO, BCM numbering):

  Device 0 — SPI0                 Device 1 — SPI1
  ─────────────────────────────   ─────────────────────────────
  VCC  → 5 V    (pin 4)           VCC  → 5 V    (pin 2)
  GND  → GND    (pin 6)           GND  → GND    (pin 9)
  CE   → GPIO17 (pin 11)          CE   → GPIO27 (pin 13)
  CSN  → GPIO8  (pin 24)          CSN  → GPIO18 (pin 12)
  SCK  → GPIO11 (pin 23)          SCK  → GPIO21 (pin 40)
  MOSI → GPIO10 (pin 19)          MOSI → GPIO20 (pin 38)
  MISO → GPIO9  (pin 21)          MISO → GPIO19 (pin 35)

  Note: 5 V VCC requires PA+LNA modules (NRF24L01+PA+LNA) which have an
  onboard 3.3 V regulator.  Standard NRF24L01+ modules are 3.3 V only.

Enable SPI0 and SPI1 in /boot/firmware/config.txt:
    dtparam=spi=on
    dtoverlay=spi1-1cs
"""

import argparse
import threading
import time
from pyrf24 import RF24, RF24_PA_LOW, RF24_1MBPS

# ─── Hardware configuration ───────────────────────────────────────────────────
#
# CE pin uses BCM GPIO numbering.
# CSN encodes the SPI bus and device: CSN = bus * 10 + device

RADIO0_CE  = 17   # GPIO17, pin 11 — SPI0  (RX role in this test)
RADIO0_CSN = 0    # spidev0.0

RADIO1_CE  = 27   # GPIO27, pin 13 — SPI1  (TX role in this test)
RADIO1_CSN = 10   # spidev1.0

MAX_PAYLOAD = 32        # NRF24L01+ hardware payload limit in bytes
RX_ADDRESS  = b'1Node'  # 5-byte pipe address


# ─── Radio initialisation ─────────────────────────────────────────────────────

def init_radio(ce_pin, csn_pin, channel, label):
    """Initialise one radio.  Raises RuntimeError if hardware not found."""
    radio = RF24(ce_pin, csn_pin)
    if not radio.begin():
        raise RuntimeError(
            f"{label}: hardware not responding — "
            f"check SPI enabled, wiring, and 3.3 V supply"
        )
    radio.setPALevel(RF24_PA_LOW)    # low power — radios are close together
    radio.setDataRate(RF24_1MBPS)
    radio.setChannel(channel)
    radio.setPayloadSize(MAX_PAYLOAD)
    radio.setAutoAck(True)
    return radio


# ─── Worker threads ───────────────────────────────────────────────────────────

def tx_worker(radio, address, count, size, results, rx_ready, tx_done):
    """
    Transmit `count` fixed-size packets.

    Waits for rx_ready before sending so the RX radio is in listen mode first.
    Sets tx_done when finished so the RX thread knows to stop draining.
    """
    radio.openWritingPipe(address)
    radio.stopListening()

    rx_ready.wait()       # wait until RX thread is listening
    time.sleep(0.05)      # small margin to let startListening() settle

    successes = 0
    payload   = bytes(range(size % 256)) if size <= 256 else bytes(size)

    start = time.monotonic()
    for _ in range(count):
        if radio.write(payload):
            successes += 1
    elapsed = time.monotonic() - start

    results["tx"] = {
        "count":     count,
        "successes": successes,
        "elapsed":   elapsed,
        "size":      size,
    }
    tx_done.set()


def rx_worker(radio, address, results, rx_ready, tx_done):
    """
    Receive packets until TX is done and the FIFO has been drained.

    Sets rx_ready once startListening() has been called so the TX thread
    knows it is safe to start sending.
    """
    radio.openReadingPipe(1, address)
    radio.startListening()
    rx_ready.set()          # signal TX thread: we are listening

    received   = 0
    first_time = None

    # Keep reading until TX is finished AND FIFO is empty
    while not tx_done.is_set() or radio.available():
        if radio.available():
            if first_time is None:
                first_time = time.monotonic()
            radio.read(MAX_PAYLOAD)
            received += 1
        else:
            time.sleep(0.001)   # brief yield — avoids 100 % CPU busy-wait

    elapsed = (time.monotonic() - first_time) if first_time else 0

    results["rx"] = {
        "received": received,
        "elapsed":  elapsed,
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="NRF24L01+ TX/RX throughput test",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--count", type=int, default=100,
        help="number of packets to transmit",
    )
    parser.add_argument(
        "--size", type=int, default=32,
        help=f"payload size in bytes (max {MAX_PAYLOAD})",
    )
    parser.add_argument(
        "--channel", type=int, default=76,
        metavar="0-124",
        choices=range(0, 125),
        help="RF channel  (0 = 2.400 GHz, 124 = 2.524 GHz)",
    )
    args = parser.parse_args()

    # Clamp payload size to hardware limit
    size = min(args.size, MAX_PAYLOAD)
    if args.size > MAX_PAYLOAD:
        print(f"⚠️   Payload size capped at {MAX_PAYLOAD} bytes "
              f"(NRF24L01+ hardware limit)")

    print("=" * 55)
    print("  NRF24L01+ TX/RX Throughput Test")
    print("=" * 55)
    print(f"  Channel : {args.channel}  ({2400 + args.channel} MHz)")
    print(f"  Packets : {args.count}")
    print(f"  Payload : {size} bytes  ({size * 8} bits per packet)")
    print()

    # Initialise both radios
    try:
        radio0 = init_radio(RADIO0_CE, RADIO0_CSN, args.channel,
                            "Radio 0  CE=GPIO17  SPI0  (RX)")
        radio1 = init_radio(RADIO1_CE, RADIO1_CSN, args.channel,
                            "Radio 1  CE=GPIO27  SPI1  (TX)")
    except RuntimeError as exc:
        print(f"\n❌  {exc}")
        print("    Consult the Hardware Setup and Debug Guide on Canvas.\n")
        return

    print("  ✅  Both radios initialised\n")

    # Shared state
    results  = {}
    rx_ready = threading.Event()
    tx_done  = threading.Event()

    rx_thread = threading.Thread(
        target=rx_worker,
        kwargs=dict(radio=radio0, address=RX_ADDRESS,
                    results=results, rx_ready=rx_ready, tx_done=tx_done),
        daemon=True,
    )
    tx_thread = threading.Thread(
        target=tx_worker,
        kwargs=dict(radio=radio1, address=RX_ADDRESS,
                    count=args.count, size=size,
                    results=results, rx_ready=rx_ready, tx_done=tx_done),
    )

    print("📡  Running test ...\n")
    rx_thread.start()
    tx_thread.start()
    tx_thread.join()
    rx_thread.join(timeout=3.0)   # drain window after TX finishes

    # ── Report ────────────────────────────────────────────────────────────────
    tx_r = results.get("tx", {})
    rx_r = results.get("rx", {})

    tx_count     = tx_r.get("count",     args.count)
    tx_successes = tx_r.get("successes", 0)
    tx_elapsed   = tx_r.get("elapsed",   1e-9)
    rx_received  = rx_r.get("received",  0)
    rx_elapsed   = rx_r.get("elapsed",   1e-9)

    tx_bps = (tx_successes * size * 8 / tx_elapsed) if tx_elapsed > 0 else 0
    rx_bps = (rx_received  * size * 8 / rx_elapsed) if rx_elapsed > 0 else 0
    loss   = tx_count - rx_received

    print("─" * 55)
    print("  Results")
    print("─" * 55)
    print(f"  TX   {tx_successes:>5}/{tx_count}  ACKed "
          f"({100 * tx_successes / tx_count:5.1f}%)  "
          f"in {tx_elapsed:.3f} s")
    print(f"  TX throughput (ACKed packets):   {tx_bps / 1000:7.1f} kbps")
    print()
    print(f"  RX   {rx_received:>5} packets received  "
          f"in {rx_elapsed:.3f} s")
    if rx_received > 0:
        print(f"  RX throughput (received packets): {rx_bps / 1000:7.1f} kbps")
    print()
    print(f"  Packet loss: {loss}/{tx_count}  ({100 * loss / tx_count:.1f}%)")
    print("─" * 55)

    if loss > 0:
        print("\n  Tip: some loss is normal at close range with RF24_PA_LOW.")
        print("  Persistent loss → check SPI1 wiring and /boot/firmware/config.txt.\n")

    radio0.powerDown()
    radio1.powerDown()


if __name__ == "__main__":
    main()
