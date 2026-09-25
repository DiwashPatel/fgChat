import os


PORT = "5050"

print(f"Listening to TCP traffic on port {PORT}. Press Ctrl+C to stop.", flush=True)
os.execvp("tcpdump", ["tcpdump", "-i", "lo0", "-nn", "-X", "tcp", "port", PORT])
