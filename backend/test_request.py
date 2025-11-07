import requests
import json

url = "http://127.0.0.1:8000/quote"
data = {
    "upload_lat": 55.75,
    "upload_lon": 37.61,
    "transport_type": "manipulator",
    "items": [
        {"category": "ФБС БЛОКИ", "subtype": "ФБС 12-6-6", "quantity": 3}
    ]
}

response = requests.post(url, json=data)
print("✅ Ответ сервера:")
print(response.status_code)
print(json.dumps(response.json(), ensure_ascii=False, indent=2))
