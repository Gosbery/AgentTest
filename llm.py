# llm.py
import os
from openai import OpenAI
from dotenv import load_dotenv
from tools import TOOL_SCHEMAS

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL"),
)


def call_llm(messages):
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "qwen-plus"),
        messages=messages,
        tools=TOOL_SCHEMAS,
        tool_choice="auto",
    )

    return response.choices[0].message