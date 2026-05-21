#!/bin/bash

# Remove the default route through the tunnel
sudo ip route del default via 10.0.0.1 dev tun0 2>/dev/null

# Remove the route for the tunnel subnet
sudo ip route del 10.0.0.0/24 dev tun0 2>/dev/null

# Bring the interface down
sudo ip link set tun0 down 2>/dev/null

# Remove the IP address
sudo ip addr flush dev tun0 2>/dev/null

# Delete the TUN interface
sudo ip tuntap del dev tun0 mode tun 2>/dev/null

# Optionally restore DNS (systemd-resolved example)
if systemctl is-active --quiet systemd-resolved; then
    sudo ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
    sudo systemctl restart systemd-resolved
fi

echo "Tunnel teardown complete."
