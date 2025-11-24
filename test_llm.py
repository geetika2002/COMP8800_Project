import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def analyze_logs(log_text):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a cybersecurity analyst. Summarize attacker intent."},
            {"role": "user", "content": f"Here are the commands:\n{log_text}"}
        ]
    )
    return response.choices[0].message.content

if __name__ == "__main__":
    sample = "ls; whoami; cat /etc/passwd"
    print("\n--- MODEL OUTPUT ---\n")
    print(analyze_logs(sample))
