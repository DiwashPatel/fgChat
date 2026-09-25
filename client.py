import socket
import threading

from protocol import FrameType, receive_frame, send_frame

HOST = "127.0.0.1"
PORT = 5000


def receive_messages(client):
    """Continuously receive broadcasts from the server."""
    while True:
        try:
            frame = receive_frame(client)

            if frame.frame_header.frame_type == FrameType.DATA:
                print(f"\n{frame.payload.decode(errors='replace')}")
            elif frame.frame_header.frame_type == FrameType.CLOSE:
                print("\nServer disconnected.")
                break
            print("> ", end="", flush=True)

        except (ConnectionError, OSError):
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

            send_frame(client, FrameType.DATA, (message + "\n").encode())

    except ConnectionRefusedError:
        print(f"Could not connect to {HOST}:{PORT}")

    finally:
        client.close()


if __name__ == "__main__":
    main()
