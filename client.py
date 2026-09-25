import base64
import json
import socket
import threading

from nacl.exceptions import CryptoError
from nacl.public import Box, PrivateKey, PublicKey

from protocol import FrameType, ProtocolError, receive_frame, send_frame

HOST = "127.0.0.1"
PORT = 5050


class ChatClient:
    def __init__(self, sock):
        self.socket = sock
        self.private_key = PrivateKey.generate()
        self.box = None

    def send(self, message):
        send_frame(self.socket, FrameType.DATA, json.dumps(message, separators=(",", ":")).encode())

    def start_chat(self, username, encoded_key):
        try:
            public_key = PublicKey(base64.b64decode(encoded_key, validate=True))
            box = Box(self.private_key, public_key)
        except (ValueError, TypeError):
            print("\nReceived an invalid public key.")
            return
        self.box = box
        print(f"\nEncrypted chat started with @{username}. Type /leave to leave.")

    def handle(self, message):
        kind = message.get("type")
        if kind == "registered":
            print(f"\nYour username is @{message['username']}. Type @xyz to request a chat.")
        elif kind == "hello":
            username = message["from"]
            print(f"\n@{username} wants to chat. Type /accept {username} or /reject {username}.")
        elif kind in ("accepted", "chat_started"):
            self.start_chat(message["username"], message["public_key"])
        elif kind == "message":
            if not self.box:
                return
            try:
                plaintext = self.box.decrypt(base64.b64decode(message["ciphertext"], validate=True))
                print(f"\n@{message['from']}: {plaintext.decode(errors='replace')}")
            except (CryptoError, ValueError, TypeError):
                print("\nCould not decrypt a message (it may have been altered).")
        elif kind == "request_sent":
            print(f"\nChat request sent to @{message['username']}.")
        elif kind == "rejected":
            print(f"\n@{message['username']} rejected your request.")
        elif kind in ("peer_left", "left"):
            self.box = None
            print("\nChat ended. Type @xyz to start another.")
        elif kind == "error":
            print(f"\nError: {message['message']}")

    def receive_messages(self):
        try:
            while True:
                frame = receive_frame(self.socket)
                if frame.frame_header.frame_type == FrameType.DATA:
                    message = json.loads(frame.payload)
                    if isinstance(message, dict):
                        self.handle(message)
                elif frame.frame_header.frame_type == FrameType.CLOSE:
                    break
                print("> ", end="", flush=True)
        except (ConnectionError, OSError, ProtocolError, json.JSONDecodeError):
            pass
        print("\nDisconnected from server.")

    def handle_input(self, text):
        if text.startswith("/accept "):
            username = text.split(maxsplit=1)[1].removeprefix("@")
            self.send({"type": "accept", "username": username})
        elif text.startswith("/reject "):
            username = text.split(maxsplit=1)[1].removeprefix("@")
            self.send({"type": "reject", "username": username})
        elif text == "/leave":
            self.send({"type": "leave"})
        elif text.startswith("@") and " " not in text:
            self.send({"type": "connect", "username": text[1:]})
        else:
            if not self.box:
                print("Start a chat first by typing @xyz.")
                return
            ciphertext = base64.b64encode(self.box.encrypt(text.encode())).decode()
            self.send({"type": "message", "ciphertext": ciphertext})


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((HOST, PORT))
        client = ChatClient(sock)
        public_key = base64.b64encode(bytes(client.private_key.public_key)).decode()
        client.send({"type": "register", "public_key": public_key})
        threading.Thread(target=client.receive_messages, daemon=True).start()

        while True:
            text = input("> ").strip()
            if text.lower() in ("quit", "exit"):
                break
            if text:
                client.handle_input(text)
    except ConnectionRefusedError:
        print(f"Could not connect to {HOST}:{PORT}")
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        sock.close()


if __name__ == "__main__":
    main()
