# Step 1
Set up a TUN interface and IP routing for the mobile unit
```bash
chmod +x startup.sh # if needed, make it executable
./startup.sh
```
# Step 2
Set up venv in project directory: `/home/eitn30_mobile/Mobile-Unit`
```bash
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
```
# Step 3
Run tests to check radio connection
```bash
cd nrf/
python3 nrf-test-v2.py
python3 nrf-rxtx-test-v2.py
```
# Step 4
Open up TUN loop in one terminal
```bash
cd tun/
python3 open_tun_loop.py
```
(Make sure base-station is set up to this point too)
In another terminal:
```bash
ping 8.8.8.8
``` 
# Step 5
Performance measurements
```bash
cd performance/
python3 iperf3.py
```
Plot data to png files
```bash
python3 plot_performance.py
```
