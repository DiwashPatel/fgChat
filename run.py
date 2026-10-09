"""WSGI entry point for Flask and Flask-SocketIO servers."""

from app import create_app
from app.extensions import socketio

app = create_app()

if __name__ == "__main__":
    import os

    socketio.run(
        app,
        host=os.environ.get("FGCHAT_HOST", "127.0.0.1"),
        port=int(os.environ.get("FGCHAT_PORT", "5000")),
        debug=False,
        allow_unsafe_werkzeug=True,
    )
