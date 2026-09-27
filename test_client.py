from llm_client import chat_json, unload
from pydantic import BaseModel, Field


# 1. تحديد شكل البيانات المطلوب إرجاعها
class VideoReview(BaseModel):
  topic: str = Field(description="الموضوع الأساسي للفيديو")
  rating: int = Field(description="التقييم من 1 لـ 10", ge=1, le=10)
  is_exciting: bool = Field(description="هل المقطع فيه حماس؟")


# 2. إرسال نص ليقوم النموذج بتحليله
prompt = "الفيديو عبارة عن مناقشة حماسية جداً بين اتنين عن رواتب مبرمجين الذكاء الاصطناعي."

result = chat_json(
    model="qwen3:4b"
    prompt=prompt,
    schema=VideoReview,
    think=False,
)

# 3. طباعة القيم للتأكد من استخراجها ككائن بايثون
print("Topic:", result.topic)
print("Rating:", result.rating)
print("Is Exciting:", result.is_exciting)

# 4. تفريغ النموذج من الذاكرة
unload("qwen3:4b")
print("Model unloaded successfully!")