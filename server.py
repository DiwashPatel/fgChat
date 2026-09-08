import socket
import os
import threading

HOST = "127.0.0.1"
PORT = 5000

clients = []

def broadcast(message):
    for client in clients:
        client.sendall(message.encode()) # since, message was decoded (it became from bytes to str). So again making it bytes.

def handle_client(client_socket, address):

    print(f"{address} connected")

    while True:
        data = client_socket.recv(1024) # Not: server.recv()

        if not data:
            break

        message = data.decode()

        print(f"{address}: {message}")
        broadcast(message)

    client_socket.close()

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

server.bind((HOST, PORT))

server.listen()
print(f"Server started...")
print(f"\n Details: IP: {HOST} Port: {PORT} ProcessID: {os.getpid()}")

try:
    while True:
        client_socket, address = server.accept()

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