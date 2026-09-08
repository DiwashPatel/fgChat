import socket
import os

HOST = "127.0.0.1"
PORT = 5000

print(f"PID: {os.getpid()}")

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

print(f"socket created.")
print(f"Socket: {s}\n. It's Fd is {s.fileno()}\n and Addresss is: {s.getsockname()}")

s.bind((HOST, PORT))

print(f"\nBind done:")
print(f"Socket: {s}\n. It's Fd is {s.fileno()}\n and Addresss is: {s.getsockname()}")

input("\n Press Enter for the socket to listen")

# Just creating a socke or listening doesn't mean a TCP Connection. 
s.listen()
print(f"Listening started.")
print(f"Socket: {s}\n. It's Fd is {s.fileno()}\n and Addresss is: {s.getsockname()}")

input(f"Pausing this script. The port is listening though.")

# Note: It's just listening. Not accepted. An additional FD will be created for established conenction.
# It's like Listening socket. A new Connected Socket will be created.


# Note: this will only accept one connection, since it will start receiving then.
# This is not suitable for multi-chat/person. 

# Here, we can use netcat as a client. 

client, address = s.accept()
# NOTE: The accept code is a BLocking operation. If there is no avaialble conenction, it keeps waiting. 
print(f"Accepted connection")
print(f"Socket: {s}\n. It's Fd is {s.fileno()}\n and Addresss is: {s.getsockname()}")

print(f"\n Accepted connected socket client is:")
print(f"Socket: {client}\n. It's Fd is {client.fileno()}\n and Addresss is: {client.getsockname()}")
print(f"Addresss of client is: {address}")

print(f"\n not calling recv. Press Enter to receive sth from buffer if any.")
input("\n Paused.Press enter. ")
# Note: -> When we press Enter in netcat, it also counts as a byte.
# Note: -> this is also blocking. it keeps waiting.
# Note: -> We called .recv fn just once. So, it will only take message from the buffer one time. and done.

data = client.recv(1024) # upto 1024 bytes.

print(f"Data: {data}")
print(f"Number of bytes: {len(data)}")

input(f"\n Press Enter to close.")

client.close()
s.close()
