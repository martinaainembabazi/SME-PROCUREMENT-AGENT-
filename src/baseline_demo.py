from model_client import ModelClient
from prompt_loader import load_prompt

client = ModelClient()
system, user_template, version = load_prompt()

user_input = "List 3 things an SME owner should check before reordering stock."
prompt = user_template.format(input=user_input)

print(f"[Using prompt version: {version}]\n")
response = client.generate(prompt=prompt, system_instruction=system)
print(response)