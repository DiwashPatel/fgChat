import socket
import os
import threading

from protocol import FrameType, ProtocolError, receive_frame, send_frame

HOST = "127.0.0.1"
PORT = 5000

clients = []

# Creating a Lock Object. If one thread tries to remove a client and other tries to broadcast, it will cause list changed during iteration error.
clients_lock = threading.Lock()

# Also, we can't change the list during iteration, so removing the client in case of exception is also chaning the list. so better to list all dead sockets and then later remove.
def remove_client(client_socket):

    #Remove from our client list
    with clients_lock:
        # Check if client. inside the lock. not outside the lock, otherwise other may have changed, and .remove can cause error.
        if client_socket in clients:
            clients.remove(client_socket) # No problem, since client sockets are always unique.
    #Close the socket.
    try:
        client_socket.close()
        print(f"Client {client_socket} closed")
    except OSError:
        pass

    
def broadcast(source, data):
    
    with clients_lock:
        current_clients = clients[:]

    # Since, network I/0 can be slow, better to do outside the lock.
    for client in current_clients:
        try:
            if client != source:
                send_frame(client, FrameType.DATA, data)
        except OSError:
            remove_client(client)


def handle_client(client_socket, address):

    print(f"{address} connected")

    try:
        while True:
            frame = receive_frame(client_socket)

            if frame.frame_header.frame_type != FrameType.DATA:
                continue

            data = frame.payload
            message = data.decode(errors="replace")

            print(f"{address}: {message}")
            broadcast(client_socket, data)
    except (ConnectionError, OSError, ProtocolError):
        pass
    finally:
        remove_client(client_socket)
        

    client_socket.close()

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

server.bind((HOST, PORT))

server.listen()

print(f"Server started...")
print(f"\n Details: IP: {HOST} Port: {PORT} ProcessID: {os.getpid()}")

try:
    while True:
        client_socket, address = server.accept()

        with clients_lock:
            clients.append(client_socket)

        thread = threading.Thread(
            target=handle_client,
            args=(client_socket, address)
        )

        thread.start()
except KeyboardInterrupt:
    print(f"\nStopping Server: keyboard interrupt occured.")
finally:
    for client in clients:
        client.close()
    server.close()
