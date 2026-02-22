from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Tuple

import boto3
import streamlit as st
import yaml


CONFIG_FILE = Path(__file__).with_name(".bedrock_agentcore.yaml")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")


def load_agent_runtime_details() -> Tuple[str, str]:
    runtime_arn = os.getenv("AGENT_RUNTIME_ARN")
    region = os.getenv("AWS_REGION", "us-west-2")

    if runtime_arn:
        return runtime_arn, region

    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            "Set AGENT_RUNTIME_ARN or add .bedrock_agentcore.yaml to auto-load runtime ARN."
        )

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    default_agent = config.get("default_agent")
    agents = config.get("agents", {})
    if default_agent not in agents:
        raise KeyError(f"Default agent '{default_agent}' not found in .bedrock_agentcore.yaml")

    agent_cfg = agents[default_agent]
    runtime_cfg = agent_cfg.get("bedrock_agentcore", {})
    aws_cfg = agent_cfg.get("aws", {})

    runtime_arn = runtime_cfg.get("agent_arn")
    region = aws_cfg.get("region", region)

    if not runtime_arn:
        raise ValueError(
            f"No deployed runtime ARN for default agent '{default_agent}'. "
            "Deploy the agent or set AGENT_RUNTIME_ARN."
        )

    return runtime_arn, region


@st.cache_resource(show_spinner=False)
def bedrock_client(region: str):
    return boto3.client("bedrock-agentcore", region_name=region)


def invoke_runtime(
    prompt: str,
    actor_id: str,
    thread_id: str,
    runtime_arn: str,
    region: str,
) -> str:
    payload = {
        "prompt": prompt,
        "actor_id": actor_id,
        "thread_id": thread_id,
    }
    request = {
        "agentRuntimeArn": runtime_arn,
        "contentType": "application/json",
        "accept": "application/json",
        "payload": json.dumps(payload).encode("utf-8"),
    }
    # AWS runtimeSessionId has a strict min length requirement; only send when valid.
    if len(thread_id) >= 33:
        request["runtimeSessionId"] = thread_id

    response = bedrock_client(region).invoke_agent_runtime(**request)
    body = response["response"].read().decode("utf-8")
    data = json.loads(body)
    return data.get("result", "No result returned by runtime.")

def main() -> None:
    st.set_page_config(page_title="FAQ Chatbot", page_icon=":speech_balloon:")
    st.title("FAQ Chatbot")
    st.caption("Streamlit frontend invoking deployed Bedrock AgentCore runtime")

    try:
        runtime_arn, region = load_agent_runtime_details()
    except Exception as exc:
        st.error(f"Runtime configuration error: {exc}")
        return

    with st.sidebar:
        st.subheader("Memory Session")
        actor_id = st.text_input("Actor ID", value="default-user")
        thread_id = st.text_input("Thread ID", value="streamlit-session")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("Ask a question about the FAQ")
    if not prompt:
        return

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                answer = invoke_runtime(
                    prompt=prompt,
                    actor_id=actor_id,
                    thread_id=thread_id,
                    runtime_arn=runtime_arn,
                    region=region,
                )
            except Exception as exc:
                answer = f"Error: {exc}"
            st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    main()
