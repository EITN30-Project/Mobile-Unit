import os
import fcntl
import struct
import threading
import queue
import time

from pyrf24 import RF24, RF24_PA_LOW, RF24_1MBPS

# ─── TUN Setup ───────────────────────────────────────────────

TUNSETIFF = 0x400454ca
IFF_TUN = 0x0001
IFF_NO_PI = 0x1000

def open_tun(name="tun0"):
    tun_fd = os.open("/dev/net/tun", os.O_RDWR)
    ifr = struct.pack("16sH", name.encode(), IFF_TUN | IFF_NO_PI)
    fcntl.ioctl(tun_fd, TUNSETIFF, ifr)
    return tun_fd

# ─── Radio Setup (adapt to your chosen library) ─────────────

# from pyrf24 import RF24, RF24_PA_LOW, RF24_1MBPS
# radio_tx = RF24(17, 0)   # Device 1: SPI0
# radio_rx = RF24(27, 10)  # Device 2: SPI1
# ... configure both radios ...
CHANNEL = 76
ADDR_BASE = b"BASE1"
ADDR_MOBILE = b"MOBI1"

def init_radio(ce_pin, csn_pin, tx_addr, rx_addr, label, listen=True):
    radio = RF24(ce_pin, csn_pin)

    if not radio.begin():
        print(f"{label}: hardware not responding")
        return None

    radio.setPALevel(RF24_PA_LOW) # Power Amplifier  - Ctrls tx strength
    radio.setDataRate(RF24_1MBPS)  # controls tx speed
    radio.setChannel(CHANNEL)

    radio.setAutoAck(True)
    radio.enableDynamicPayloads() # to override the default fix packet length.

    # Pipes
    radio.openWritingPipe(tx_addr) # only one pipe at a time
    radio.openReadingPipe(1, rx_addr) # can have up to 6 rx pipes.

    if listen:
        radio.startListening()
    else:
        radio.stopListening()

    print(f"{label}: ready (channel {CHANNEL})")
    return radio

# ─── Queues ──────────────────────────────────────────────────

tx_queue = queue.Queue(maxsize=100)  # TUN → Radio
rx_queue = queue.Queue(maxsize=100)  # Radio → TUN

# ─── Fragmentation ──────────────────────────────────────────────────
FRAGMENT_SIZE = 29  # 32 - 3 byte header: packet id (1 byte), fragment index (1 byte), total fragments (1 byte)
FRAGMENT_TIMEOUT = 2

_packet_id_lock = threading.Lock()      # TODO: use itertools.count() instead???
_packet_id_counter = 0

# prevents race condition for counter --> only one thread should be able to call fragment_packet() at a time, but in case that breaks
def next_packet_id():
    global _packet_id_counter
    with _packet_id_lock:
        _packet_id_counter = (_packet_id_counter + 1) % 256
        return _packet_id_counter

def fragment_packet(packet):
    """Split an IP packet into NRF24-sized fragments."""
    fragments = []
    total = (len(packet) + FRAGMENT_SIZE - 1) // FRAGMENT_SIZE

    if total > 256:
        raise ValueError(f"Packet too large: {len(packet)} bytes produces {total} fragments (max 256)")

    pkt_id = next_packet_id()

    for i in range(total):
        offset = i * FRAGMENT_SIZE
        chunk = packet[offset:offset + FRAGMENT_SIZE]
        header = struct.pack("BBB", pkt_id, i, total)
        fragments.append(header + chunk)
    return fragments

# ─── Thread Functions ────────────────────────────────────────

def tun_reader(tun_fd, tx_q):
    """Read IP packets from TUN and put them on the TX queue."""
    while True:
        packet = os.read(tun_fd, 2048)
        if packet:
            tx_q.put(packet, timeout=1)        # can block forever without timeout

def radio_writer(radio, tx_q):
    """Take packets from the TX queue and send them over the radio."""    
    while True:
        packet = tx_q.get()
        try:
            fragments = fragment_packet(packet)
            for frag in fragments:
                success = radio.write(frag)
                if not success:
                    print(f"[radio_writer] fragment send failed, dropping packet")
                    # TODO: keep track of dropped packets later
                    break
        except Exception as e:
            print(f"[radio_writer] error: {e}")
        finally:
            tx_q.task_done()

def radio_reader(radio, rx_q):
    """Read data from the radio and put it on the RX queue."""
    while True:
        if radio.available():
            data = radio.read(32)
            rx_q.put(bytes(data))
        # Small sleep to avoid busy-waiting (tune this!)
        time.sleep(0.001)

# use a dictionary of reassembly buffers --> replace fragments=[] with:
# packets = {
#     pkt_id: {
#         "fragments": {},
#         "total": N,
#         "timestamp": time.time()
#     }
# }
def tun_writer(tun_fd, rx_q):
    """Take packets from the RX queue and write them to TUN."""
    packets = {}
    while True:
        fragment = rx_q.get() # random fragment, not in order
        #TODO: Catch queue.Empty?? --> flush_expired()
        #TODO: check len(fragment) < 3 and discard??

        # retrieve index and total from header
        pkt_id = fragment[0]
        index = fragment[1]
        total = fragment[2]
        payload = fragment[3:]

        if pkt_id not in packets:
            packets[pkt_id] = {
                "fragments": {},
                "total": total,
                "timestamp": time.time()
            }

        packet = packets[pkt_id]

        # Guard against a mismatched 'total' field across fragments of the same packet
        if packet["total"] != total:
            print(f"[tun_writer] pkt_id={pkt_id} total mismatch ({packet['total']} vs {total}), dropping")
            del packets[pkt_id]
            rx_q.task_done()
            continue

        packet["fragments"][index] = payload

        # check if we now have a complete full packet --> reassemble_fragments
        if len(packet["fragments"]) == packet["total"]:
            # confirm that no index was skipped or doubled
            if set(packet["fragments"].keys()) == set(range(packet["total"])):
                full_packet = b"".join(packet["fragments"][i] for i in range(packet["total"]))
                os.write(tun_fd, full_packet)
            else:
                print(f"[tun_writer] pkt_id={pkt_id} index gap detected, dropping")
            del packets[pkt_id]
        
        # clean up
        flush_expired(packets)

        rx_q.task_done()

def flush_expired(packets, timeout=FRAGMENT_TIMEOUT):
    now = time.time()
    expired = [
        pid for pid, p in packets.items()
        if now - p["timestamp"] > timeout
    ]
    for pid in expired:
        packet = packets[pid]
        print(f"[tun_writer] dropping expired packet id={pid}: "
              f"got {len(packet['fragments'])}/{packet['total']} fragments")
        del packets[pid]

# ─── Main ────────────────────────────────────────────────────

def main():
    tun = open_tun("tun0")

    # mobile -> base
    radio_tx = init_radio(
        ce_pin=17,
        csn_pin=0,
        tx_addr=ADDR_BASE,
        rx_addr=ADDR_MOBILE,
        label="TX radio",
        listen=False
    )
    # base -> mobile
    radio_rx = init_radio(
        ce_pin=27,
        csn_pin=10,
        tx_addr=ADDR_BASE,
        rx_addr=ADDR_MOBILE,
        label="RX radio",
        listen=True
    )

    # Start threads (daemon=True so they stop when main exits)
    threads = [
        threading.Thread(target=tun_reader, args=(tun, tx_queue), daemon=True),
        threading.Thread(target=radio_writer, args=(radio_tx, tx_queue), daemon=True),
        threading.Thread(target=radio_reader, args=(radio_rx, rx_queue), daemon=True),
        threading.Thread(target=tun_writer, args=(tun, rx_queue), daemon=True),
    ]

    for t in threads:
        t.start()

    print("Radio relay running. Press Ctrl+C to stop.")

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("\nStopping.")

if __name__ == "__main__":
    main()

#TX radio (mobile → base)
#    tx_addr = b"BASE1"
#    rx_addr = b"MOBI1"
#RX radio (base → mobile)
#    tx_addr = b"MOBI1"
#    rx_addr = b"BASE_RX"
