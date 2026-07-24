from nemoguardrails.actions import action
from typing import Optional
import os

_fasttext_model = None

def _get_fasttext_model():
    global _fasttext_model
    if _fasttext_model is None:
        import fasttext
        fasttext.FastText.eprint = lambda x: None
        model_path = "/tmp/lid.176.ftz"
        if not os.path.exists(model_path):
            import urllib.request
            urllib.request.urlretrieve(
                "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz",
                model_path
            )
        _fasttext_model = fasttext.load_model(model_path)
    return _fasttext_model

@action(is_system_action=True)
async def check_forbidden_words(context: Optional[dict] = None) -> str:
    user_message = context.get("user_message", "").lower()
    FORBIDDEN_WORDS = ["hack", "exploit", "violence", "illegal"]
    for word in FORBIDDEN_WORDS:
        if word in user_message:
            return "blocked"
    return "allowed"

@action(is_system_action=True)
async def check_language(context: Optional[dict] = None) -> str:
    user_message = context.get("user_message", "").strip()
    try:
        model = _get_fasttext_model()
        predictions = model.predict(user_message.replace("\n", " "))
        detected_lang = predictions[0][0].replace("__label__", "")
        confidence = predictions[1][0]
        if detected_lang in ("sk", "cs") or confidence < 0.5:
            return "allowed"
        return "blocked"
    except Exception:
        return "allowed"
