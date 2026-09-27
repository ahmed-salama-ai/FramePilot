import ollama

# 1. بنعرف الأداة اللي الموديل مسموح له يستخدمها
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather in a given city",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "The city to get weather for",
                    }
                },
                "required": ["city"],
            },
        },
    }
]

# 2. بنبعت سؤال للموديل محتاج الأداة دي
response = ollama.chat(
    model="qwen3:8b",
    messages=[{"role": "user", "content": "How is the weather in Cairo?"}],
    tools=tools,
)

# 3. بنطبع رد الموديل
print("Tool calls from model:")
print(response.message.tool_calls)