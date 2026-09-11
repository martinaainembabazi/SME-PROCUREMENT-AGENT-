from model_client import ModelClient

client = ModelClient()
response = client.generate(
    prompt="List 3 things an SME owner should check before reordering stock.",
    system_instruction="You are a procurement assistant for small businesses in Uganda."
)
print(response)