import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Type
import ollama
from pydantic import BaseModel, ValidationError


def chat_json(
    model: str,
    prompt: str,
    schema: Type[BaseModel],
    images: Optional[List[str | Path]] = None,
    temperature: float = 0.2,
    think: Optional[bool] = None,
    keep_alive: str = "2m",
) -> BaseModel:
  """تسأل الموديل وتجبره يرجع النتيجة مطابقة لنموذج Pydantic بدقة."""
  msg: Dict[str, Any] = {"role": "user", "content": prompt}

  # لو بنبعت صورة لموديل الـ VLM (زي تحليل شبكة الكاميرات)
  if images:
    msg["images"] = [str(p) for p in images]

  extra = {}
  # لموديلات qwen3: إلغاء التفكير (think=False) بيخلي الرد أسرع بكتير
  if think is not None:
    extra["think"] = think

  # بنعطي الموديل فرصة تانية (محاولتين) لو أول مرة الـ JSON مكنش مظبوط
  for attempt in range(2):
    response = ollama.chat(
        model=model,
        messages=[msg],
        format=schema.model_json_schema(),  # بنجبر Ollama يلتزم بـ Schema محددة
        options={"temperature": temperature, "keep_alive": keep_alive, **extra},
    )

    try:
      # بنحول الرد لنفس كائن Pydantic ونتأكد من صحة الداتا
      return schema.model_validate_json(response.message.content)
    except ValidationError:
      # لو فشل في أول محاولة، بيعيد تاني، لو فشل في التانية بيطلع الخطأ
      if attempt == 1:
        raise


def unload(model: str):
  """تفريغ كارت الشاشة (GPU) فوراً ومسح الموديل من الذاكرة."""
  ollama.generate(model=model, prompt="", keep_alive=0)