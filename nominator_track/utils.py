import asyncio
import sys

server = None


async def get_refresh_token(client, authorization_url, token_url, **kwargs):
    global server

    print("In order to continue, you need to input your osu! access token.")
    uri, state = client.create_authorization_url(
        authorization_url, redirect_uri="http://127.0.0.1:8080/"
    )
    print("Please open the following URL: " + uri)
    sys.stdout.flush()

    server = await asyncio.start_server(on_connect, "127.0.0.1", 8080)
    try:
        await server.serve_forever()
    except asyncio.CancelledError:
        pass

    callback_path = input("Code from browser: ")
    param_tokens = callback_path.split("?", 1)[1].split("&")
    params = {k: v for (k, v) in [token.split("=") for token in param_tokens]}

    if state != params["state"]:
        err = "State mismatch. Expected: {} Received: {}".format(state, params["state"])
        raise ValueError(err)
    elif "error" in params:
        raise Exception(params["error"])

    token = await client.fetch_token(
        token_url, authorization_response=callback_path, **kwargs
    )

    return token


async def _send(writer, message):
    global server

    writer.write("HTTP/1.1 200 OK\r\n\r\n{}".format(message).encode("utf-8"))
    await writer.drain()
    writer.close()
    await writer.wait_closed()
    server.close()
    await server.wait_closed()


async def on_connect(reader, writer):
    data = await reader.read(1024)
    data = data.decode()
    callback_path = data.split(" ", 2)[1]
    await _send(
        writer, "Come back to console and copy paste the following: " + callback_path
    )
