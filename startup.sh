#!/bin/bash

# Create the TUN interface
sudo ip tuntap add dev tun0 mode tun user eitn30_mobile

# Assign an IP address
sudo ip addr add 10.0.0.2/24 dev tun0

# Bring the interface up
sudo ip link set tun0 up

# Route all traffic for the base station's network through the tunnel
sudo ip route add 10.0.0.0/24 dev tun0

# Default route through the base station (for Internet access)
sudo ip route add default via 10.0.0.1 dev tun0

# Set DNS so name resolution works
echo "nameserver 8.8.8.8" | sudo tee /etc/resolv.conf

# Make sure it does not default through wlan0 when TUN IP is blocked
sudo ip route del default via 10.15.10.180 dev wlan0
