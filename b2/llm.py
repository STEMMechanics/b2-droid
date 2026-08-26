"""OpenAI-compatible local inference transport."""

import time

import requests


class LLMClient:
    def __init__(self, endpoint):
        self.endpoint = endpoint

    def chat(self, messages, temperature=0.8, max_tokens=60, timeout=60,
             request_kind="foreground"):
        started = time.monotonic()
        print(
            f"AI request started: kind={request_kind}, messages={len(messages)}, "
            f"timeout={timeout}s"
        )
        try:
            response = requests.post(
                self.endpoint,
                json={
                    "messages": messages, "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=timeout,
            )
            try:
                response.raise_for_status()
            except requests.HTTPError as error:
                # llama.cpp normally explains 400 responses in JSON. Include a
                # bounded response body so diagnostics reveal context/template
                # errors instead of only saying "Bad Request".
                detail = response.text.strip().replace("\n", " ")[:800]
                if detail:
                    raise requests.HTTPError(
                        f"{error}; response={detail}", response=response
                    ) from error
                raise
            answer = response.json()["choices"][0]["message"]["content"].strip()
        except Exception as error:
            print(
                f"AI request failed: kind={request_kind}, "
                f"elapsed={time.monotonic() - started:.1f}s, error={error}"
            )
            raise
        print(
            f"AI request completed: kind={request_kind}, "
            f"elapsed={time.monotonic() - started:.1f}s"
        )
        return answer

    def available(self, timeout=2):
        base = self.endpoint.rsplit("/v1/chat/completions", 1)[0]
        try:
            response = requests.get(base + "/health", timeout=timeout)
            return response.ok, response.json()
        except Exception as error:
            return False, {"error": str(error)}
