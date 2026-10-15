import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

api_key = os.getenv("NVIDIA_API_KEY")

if not api_key:
    raise ValueError("NVIDIA_API_KEY is missing from your .env file.")

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=api_key,
)

response = client.chat.completions.create(
  model="google/gemma-4-31b-it",
    messages=[
        {
            "role": "user",
            "content": (
                "Write a formal, two-sentence press note "
                "announcing a student cybersecurity awareness "
                "event in Jaipur. Do not invent attendance "
                "figures, guest names, or quotes."
            ),
        }
    ],
    temperature=0.2,
    max_tokens=200,
)

print(response.choices[0].message.content)