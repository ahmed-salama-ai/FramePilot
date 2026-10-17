import ollama
from pydantic import BaseModel, ValidationError


def chat_json(model: str, prompt: str, schema: type[BaseModel], images: list | None = None,
              temperature: float = 0.2, think: bool | None = None, keep_alive: str | int = "2m") -> BaseModel:
    """Ask a model; force the answer into the Pydantic schema. Returns a schema object."""
    msg = {"role": "user", "content": prompt}
    if images:
        msg["images"] = [str(p) for p in images]
    extra = {"think": think} if think is not None else {}
    for attempt in range(2):                                          #one retry if the json is bad
        r = ollama.chat(model=model, messages=[msg], format=schema.model_json_schema(),
                        options={"temperature": temperature}, keep_alive=keep_alive, **extra)
        try:
            return schema.model_validate_json(r.message.content)
        except ValidationError:
            if attempt == 1:
                raise


def unload(model: str):
    ollama.generate(model=model, prompt="", keep_alive=0)
