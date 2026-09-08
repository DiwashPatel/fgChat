import socket
import os
import threading

HOST = "127.0.0.1"
PORT = 5000

def handle_client(client_socket, address):

    print(f"{address} connected")

    while True:
        data = client_socket.recv(1024) # Not: server.recv()

        if not data:
            break

        message = data.decode()

        print(f"{address}: {message}")

    client_socket.close()

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

server.bind((HOST, PORT))

server.listen()
print(f"Server started...")
print(f"\n Details: IP: {HOST} Port: {PORT} ProcessID: {os.getpid()}")


while True:
    client_socket, address = server.accept()

    thread = threading.Thread(
        target=handle_client,
        args=(client_socket, address)
    )

    thread.start()



    