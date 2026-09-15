import socket
import threading

HOST = "127.0.0.1"
PORT = 5000


def receive_messages(client):
    """Continuously receive broadcasts from the server."""
    while True:
        try:
            data = client.recv(4096)

            # recv() returning b"" means the server closed the connection
            if not data:
                print("\nServer disconnected.")
                break

            print(f"\n{data.decode(errors='replace')}")
            print("> ", end="", flush=True)

        except (ConnectionResetError, OSError):
            break


def main():
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    try:
        client.connect((HOST, PORT))
        print(f"Connected to {HOST}:{PORT}")

        # Separate thread constantly waits for broadcasts
        receiver_thread = threading.Thread(
            target=receive_messages,
            args=(client,),
            daemon=True
        )
        receiver_thread.start()

        # Main thread handles keyboard input
        while True:
            message = input("> ")

            if message.lower() in ("quit", "exit"):
                break

            client.sendall((message + "\n").encode())

    except ConnectionRefusedError:
        print(f"Could not connect to {HOST}:{PORT}")

    finally:
        client.close()


if __name__ == "__main__":
    main()