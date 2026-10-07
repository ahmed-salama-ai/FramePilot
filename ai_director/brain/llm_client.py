# ai_director/brain/llm_client.py — one way for everyone to ask a local Ollama model for a JSON answer
# Owner: Eslam ElKharbotly (fixed by Ahmed Salama: keep_alive and think are ollama.chat arguments, not options)
import ollama
from pydantic import BaseModel, ValidationError


def chat_json(model: str, prompt: str, schema: type[BaseModel], images: list | None = None,
              temperature: float = 0.2, think: bool | None = None, keep_alive: str | int = "2m") -> BaseModel:
    """Ask a model; force the answer into the Pydantic schema. Returns a schema object.
    images = image files (for a vision model). think=False makes qwen3 models answer without "thinking" (faster);
    leave it None for models that cannot think (e.g. moondream). keep_alive = how long the model stays in memory."""
    msg = {"role": "user", "content": prompt}
    if images:
        msg["images"] = [str(p) for p in images]
    extra = {"think": think} if think is not None else {}
    for attempt in range(2):                                          # one retry if the JSON is bad
        r = ollama.chat(model=model, messages=[msg], format=schema.model_json_schema(),
                        options={"temperature": temperature}, keep_alive=keep_alive, **extra)
        try:
            return schema.model_validate_json(r.message.content)
        except ValidationError:
            if attempt == 1:
                raise


def unload(model: str):
    """Free the GPU right now (used at the end of a pipeline stage)."""
    ollama.generate(model=model, prompt="", keep_alive=0)
