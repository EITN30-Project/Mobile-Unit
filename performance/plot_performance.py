import pandas as pd
import matplotlib.pyplot as plt

# Read the performance metrics from the CSV file
data = pd.read_csv('performance_metrics.csv')

# Plot bandwidth
def plot_throughput():
    plt.figure(figsize=(10, 6))
    plt.plot(data['input_bps'], data['output_bps'], marker='o', linestyle='-', color='b', label='Output Throughput')
    plt.title('Output Throughput vs Input Throughput')
    plt.xlabel('Input Throughput (bps)')
    plt.ylabel('Output Throughput (bps)')
    plt.grid(True)
    plt.legend()
    plt.savefig('throughput_plot.png')
    plt.show()

# Plot latency
def plot_latency():
    plt.figure(figsize=(10, 6))
    plt.plot(data['input_bps'], data['rtt_avg_ms'], marker='x', linestyle='--', color='r', label='Latency')
    plt.title('Latency (RTT) vs Input Throughput')
    plt.xlabel('Input Throughput (bps)')
    plt.ylabel('Latency (ms)')
    plt.grid(True)
    plt.legend()
    plt.savefig('latency_plot.png')
    plt.show()

# Execute plotting functions
plot_throughput()
plot_latency()
