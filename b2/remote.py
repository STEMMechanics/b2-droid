"""Optional Slack Socket Mode bridge."""

import os
import threading


def start_slack(on_message):
    bot_token = os.environ.get("B2_SLACK_BOT_TOKEN")
    app_token = os.environ.get("B2_SLACK_APP_TOKEN")
    allowed_channel = os.environ.get("B2_SLACK_ALLOWED_CHANNEL")
    if not bot_token or not app_token or not allowed_channel:
        return None
    try:
        from slack_sdk.socket_mode import SocketModeClient
        from slack_sdk.socket_mode.response import SocketModeResponse
        from slack_sdk.web import WebClient
    except ImportError:
        print("Slack configured but slack-sdk is not installed.")
        return None

    web = WebClient(token=bot_token)
    client = SocketModeClient(app_token=app_token, web_client=web)

    def handle(socket_client, request):
        if request.type != "events_api":
            return
        socket_client.send_socket_mode_response(
            SocketModeResponse(envelope_id=request.envelope_id)
        )
        event = request.payload.get("event", {})
        if (
            event.get("channel") != allowed_channel
            or event.get("bot_id")
            or not event.get("text")
        ):
            return

        def respond():
            answer = on_message(event["text"])
            if answer:
                web.chat_postMessage(channel=allowed_channel, text=answer)

        threading.Thread(target=respond, daemon=True).start()

    client.socket_mode_request_listeners.append(handle)
    client.connect()
    print("Slack remote control online.")
    return client
