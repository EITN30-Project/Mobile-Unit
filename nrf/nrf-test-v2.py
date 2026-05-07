#!/usr/bin/env python3
"""
NRF24L01+ initialisation and loopback test.

Checks that both radios are wired correctly and can communicate with each other.
Radio 0 (SPI0) receives; Radio 1 (SPI1) transmits.  Five test packets are sent
and the script reports a clear pass/fail for each one.

Install the library once:
    pip3 install pyrf24

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

See the Hardware Setup and Debug Guide pages on Canvas for full instructions.
"""

import time
from pyrf24 import RF24, RF24_PA_LOW, RF24_1MBPS

# ─── Hardware configuration ───────────────────────────────────────────────────
#
# CE pin uses BCM GPIO numbering.
# CSN encodes the SPI bus and device: CSN = bus * 10 + device
#   → 0  means /dev/spidev0.0  (SPI0, chip-select 0)
#   → 10 means /dev/spidev1.0  (SPI1, chip-select 0)

RADIO0_CE  = 17   # GPIO17, pin 11 — SPI0 (receives in this test)
RADIO0_CSN = 0    # spidev0.0

RADIO1_CE  = 27   # GPIO27, pin 13 — SPI1 (transmits in this test)
RADIO1_CSN = 10   # spidev1.0

# RF settings
CHANNEL      = 76      # 2.476 GHz — clear of most Wi-Fi
RX_ADDRESS   = b'Node0'  # 5-byte pipe address radio0 listens on
NUM_PACKETS  = 5


# ─── Helpers ─────────────────────────────────────────────────────────────────

def init_radio(ce_pin, csn_pin, label):
    """Initialise one radio and print a summary line.  Returns None on failure."""
    radio = RF24(ce_pin, csn_pin)
    if not radio.begin():
        print(f"  ❌  {label}: hardware not responding")
        print(f"       Check: SPI enabled, wiring, 3.3 V supply, no bent pins.")
        return None
    radio.setPALevel(RF24_PA_LOW)   # low power — radios are centimetres apart
    radio.setDataRate(RF24_1MBPS)
    radio.setChannel(CHANNEL)
    radio.setPayloadSize(4)         # 4-byte counter payload for this test
    radio.setAutoAck(True)
    print(f"  ✅  {label}: detected  (channel {radio.channel}, PA low, 1 Mbps)")
    return radio


def loopback_test(tx_radio, rx_radio):
    """Send NUM_PACKETS from tx_radio to rx_radio and verify each payload."""

    # Put RX radio into receive mode first
    rx_radio.openReadingPipe(1, RX_ADDRESS)
    rx_radio.startListening()

    # Put TX radio into transmit mode
    tx_radio.openWritingPipe(RX_ADDRESS)
    tx_radio.stopListening()

    print(f"\n📡  Loopback test — sending {NUM_PACKETS} packets "
          f"(radio1 → radio0) ...\n")

    passed = 0
    for i in range(NUM_PACKETS):
        payload = i.to_bytes(4, "little")

        # write() blocks until ACK received or max retries exhausted
        acked = tx_radio.write(payload)

        if not acked:
            print(f"  ❌  Packet {i}: TX failed — no ACK from radio0")
            print(f"       Is radio0 in RX mode?  Check CE/CSN wiring for SPI0.")
            continue

        # ACK received; now read from RX FIFO
        deadline = time.monotonic() + 0.25
        while not rx_radio.available() and time.monotonic() < deadline:
            pass

        if not rx_radio.available():
            print(f"  ⚠️   Packet {i}: ACK received but RX FIFO empty "
                  f"(timing issue — try again)")
            continue

        received = rx_radio.read(4)
        if bytes(received) == payload:
            print(f"  ✅  Packet {i}: OK  (payload {int.from_bytes(payload, 'little')})")
            passed += 1
        else:
            print(f"  ⚠️   Packet {i}: payload mismatch "
                  f"(sent {payload.hex()}, got {bytes(received).hex()})")

        time.sleep(0.05)

    print(f"\n  {'✅  All' if passed == NUM_PACKETS else '❌  Only'} "
          f"{passed}/{NUM_PACKETS} packets passed.\n")
    return passed == NUM_PACKETS


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 52)
    print("  NRF24L01+ Initialisation and Loopback Test")
    print("=" * 52)

    print(f"\n🔌  Initialising radios (channel {CHANNEL}) ...\n")
    radio0 = init_radio(RADIO0_CE, RADIO0_CSN, "Radio 0  CE=GPIO17  SPI0  (RX)")
    radio1 = init_radio(RADIO1_CE, RADIO1_CSN, "Radio 1  CE=GPIO27  SPI1  (TX)")

    if radio0 is None or radio1 is None:
        print("\n❌  Aborting — fix wiring before running the loopback test.")
        print("    Consult the Debug Guide on Canvas.\n")
        return

    ok = loopback_test(tx_radio=radio1, rx_radio=radio0)

    radio0.powerDown()
    radio1.powerDown()

    if not ok:
        print("  If some packets failed, check:")
        print("  • SPI1 is enabled  (dtoverlay=spi1-1cs in /boot/firmware/config.txt)")
        print("  • CE and CSN pins are not swapped")
        print("  • Both radios share a common GND")
        print("  • VCC is 3.3 V (not 5 V for standard modules)\n")


if __name__ == "__main__":
    main()
