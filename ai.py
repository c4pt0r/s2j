# ai.py, a simple llm wrapper
import os
import json
import hashlib
from openai import OpenAI
from dotenv import load_dotenv
import log

load_dotenv()

class LLM:
    def __init__(self):
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=self.openai_key)

    def _generate_cache_key(self, chat_history, model, max_tokens, json_mode):
        # Generate a unique cache key
        key_data = json.dumps({
            "chat_history": chat_history,
            "model": model,
            "max_tokens": max_tokens,
            "json_mode": json_mode
        }, sort_keys=True).encode('utf-8')
        return hashlib.md5(key_data).hexdigest()

    def _load_from_cache(self, cache_key, cache_dir):
        # Load result from cache
        cache_file = os.path.join(cache_dir, f"{cache_key}.cache")
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                return f.read()
        return None

    def _save_to_cache(self, cache_key, response, cache_dir):
        # Save result to cache
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, f"{cache_key}.cache")
        with open(cache_file, 'w') as f:
            f.write(response)

    def ask(self, 
                chat_history: list[str],
                model: str = "gpt-4o",
                max_tokens: int = 16 * 1024,
                json_mode: bool = False,
                cached_mode: bool = True,
                cache_dir: str = ".cached",
                ):
        client = self.client
        history = []
        for msg in chat_history:
            if isinstance(msg, str):
                history.append({"role": "user", "content": msg})
            else:
                history.append(msg)

        log.debug(f"asking llm: {history}")

        cache_key = self._generate_cache_key(chat_history, model, max_tokens, json_mode)
        
        if cached_mode:
            cached_response = self._load_from_cache(cache_key, cache_dir)
            if cached_response:
                log.info(f"Load from cache: {cache_key}")
                log.debug(f"cached_response: {cached_response}")
                return {"content": cached_response}

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                *history,
            ],
            max_tokens=max_tokens,
            response_format={"type": "json_object"} if json_mode else None,
        )
        
        result = response.choices[0].message.content
        
        if cached_mode:
            self._save_to_cache(cache_key, result, cache_dir)
        
        log.debug(f"result: {result}")
        return {"content": result}
