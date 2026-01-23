import requests
import json

OPENWEBUI_API_KEY="sk-d2deb463434d4ff9abf0d024842f0284"
OPENWEBUI_URL = "https://chat.agrospai.udl.cat"

GET_MODELS_URL = f"{OPENWEBUI_URL}/api/models"
CHAT_COMPLETIONS_URL = f"{OPENWEBUI_URL}/api/chat/completions"
EMBEDDINGS_URL = f"{OPENWEBUI_URL}/api/embeddings"



class OpenWebUI:
    def __init__(self, api_key: str):
       self.api_key = api_key


    def get_models(self) -> list[str]:
       models = requests.get(GET_MODELS_URL, headers={"Authorization": f"Bearer {self.api_key}"}).json()["data"]
       return [model["id"] for model in models] #model_ids


    def chat_with_model(self, token, model_id, prompt) -> dict:
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        data = {
          "model": model_id,
          "stream": False,
          "messages": [
            {
              "role": "user",
              "content": prompt
            }
          ]
        }

        
        response = requests.post(CHAT_COMPLETIONS_URL, headers=headers, json=data)
        return response.json()
    
    
