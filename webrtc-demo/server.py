
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

app = FastAPI()

clients = []


@app.get("/")
async def homepage():
    return FileResponse("index.html")


@app.websocket("/ws")
async def signaling(ws: WebSocket):
    await ws.accept()

    if len(clients) >= 2:
        await ws.close()
        return

    clients.append(ws)
    print("Client connected. Total:", len(clients))

    try:
        if len(clients) == 2:
            await clients[0].send_json({"type": "ready", "caller": True})
            await clients[1].send_json({"type": "ready", "caller": False})

        while True:
            message = await ws.receive_text()

            for client in clients:
                if client != ws:
                    await client.send_text(message)

    except WebSocketDisconnect:
        print("Client disconnected")

    finally:
        if ws in clients:
            clients.remove(ws)

        for client in clients:
            await client.send_json({"type": "left"})
