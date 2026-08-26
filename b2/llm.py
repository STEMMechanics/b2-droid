"""OpenAI-compatible inference with optional LiteLLM priority routing."""

import time


class LLMClient:
    def __init__(self, endpoint, route_store=None, completion_func=None):
        self.endpoint = endpoint
        self.route_store = route_store
        self.completion_func = completion_func
        self.last_backend = None

    def _completion(self):
        if self.completion_func:
            return self.completion_func
        try:
            from litellm import completion
            return completion
        except ImportError:
            return None

    def _routed_chat(self, messages, temperature, max_tokens, timeout, request_kind):
        completion = self._completion()
        if completion is None:
            return None
        failures = []
        for route in self.route_store.connections():
            if not route["enabled"]:
                continue
            route_timeout = min(float(timeout), route["timeout"])
            started = time.monotonic()
            print(f"AI route started: kind={request_kind}, backend={route['id']}, timeout={route_timeout}s")
            try:
                kwargs = {
                    "model": route["model"], "messages": messages,
                    "temperature": temperature, "max_tokens": max_tokens,
                    "timeout": route_timeout, "api_key": route["api_key"],
                }
                if route.get("api_base"):
                    kwargs["api_base"] = route["api_base"]
                response = completion(**kwargs)
                answer = response.choices[0].message.content.strip()
                self.last_backend = route["id"]
                print(f"AI route completed: backend={route['id']}, elapsed={time.monotonic() - started:.1f}s")
                return answer
            except Exception as error:
                failures.append(f"{route['id']}: {error}")
                print(f"AI route failed: backend={route['id']}, elapsed={time.monotonic() - started:.1f}s, error={error}")
        raise RuntimeError("all LLM connections failed: " + "; ".join(failures))

    def chat(self, messages, temperature=0.8, max_tokens=60, timeout=60,
             request_kind="foreground"):
        if self.route_store is not None:
            routed = self._routed_chat(messages, temperature, max_tokens, timeout, request_kind)
            if routed is not None:
                return routed
        started = time.monotonic()
        import requests
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
            self.last_backend = "local-ai"
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
        if self.route_store is not None:
            return True, {
                "routes": self.route_store.snapshot()["connections"],
                "last_backend": self.last_backend,
            }
        base = self.endpoint.rsplit("/v1/chat/completions", 1)[0]
        import requests
        try:
            response = requests.get(base + "/health", timeout=timeout)
            return response.ok, response.json()
        except Exception as error:
            return False, {"error": str(error)}
