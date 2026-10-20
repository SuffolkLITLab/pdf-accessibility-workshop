"""Direct OpenAI transport for explicit, human-reviewed drafting requests."""

import os


def get_first_small_model():
    return os.environ.get("OPENAI_MODEL", "gpt-5-mini")


def chat_completion(**kwargs):
    from openai import OpenAI

    model = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
    params = {
        "model": model,
        "messages": kwargs["messages"],
        "max_completion_tokens": kwargs.get("max_output_tokens", 8192),
    }
    if kwargs.get("json_mode"):
        params["response_format"] = {"type": "json_object"}
    if model.startswith(("gpt-5", "o1", "o3", "o4")):
        params["reasoning_effort"] = kwargs.get("reasoning_effort") or "low"
    elif "temperature" in kwargs:
        params["temperature"] = kwargs["temperature"]
    result = OpenAI(timeout=120, max_retries=1).chat.completions.create(**params)
    choice = result.choices[0]
    if choice.finish_reason != "stop" or not choice.message.content:
        raise ValueError("AI drafting did not return a complete answer. Try fewer items.")
    return choice.message.content
