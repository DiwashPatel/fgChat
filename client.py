import getpass
import socket
import threading

HOST = "127.0.0.1"
PORT = 5000


def receive_messages(stream):
    for line in stream:
        print(f"\n{line.rstrip()}\n> ", end="", flush=True)
    print("\nServer disconnected.")


def main():
    action = input("Register a new account or log in? [register/login]: ").strip().lower()
    if action not in ("register", "login"):
        print("Choose register or login.")
        return
    username = input("Username (3-24 letters, numbers, underscores): ").strip()
    password = getpass.getpass("Password (10-128 characters): ")

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect((HOST, PORT))
        stream = client.makefile("r", encoding="utf-8", errors="replace")
        print(stream.readline().rstrip())
        client.sendall(f"{action.upper()} {username} {password}\n".encode("utf-8"))
        result = stream.readline().rstrip()
        print(result)
        if not result.startswith("AUTH_OK "):
            return

        threading.Thread(target=receive_messages, args=(stream,), daemon=True).start()
        while True:
            message = input("> ")
            if message.lower() in ("quit", "exit"):
                break
            if "\n" not in message and len(message.encode("utf-8")) <= 4096:
                client.sendall((message + "\n").encode("utf-8"))
            else:
                print("Messages must fit on one line and be at most 4096 bytes.")
    except ConnectionRefusedError:
        print(f"Could not connect to {HOST}:{PORT}")
    except OSError as error:
        print(f"Connection error: {error}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
