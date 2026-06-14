import hashlib
import json
import os
from pathlib import Path
from typing import Any, List, Optional, Dict
from PIL import Image

class CacheManager:
    def __init__(self, cache_dir: str = '.cache'):
        """
        Initialize CacheManager with a directory.
        Defaults to '.cache' in the current working directory.
        """
        # Resolve path to be sure
        self.cache_dir = Path(cache_dir).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.stats = {'hits': 0, 'misses': 0}

    def _hash_obj(self, obj: Any) -> str:
        """Helper to hash varying types of objects."""
        if isinstance(obj, Image.Image):
            # For images, we hash the pixel data
            # Converting to RGB ensures consistency (dropping alpha channel if irrelevantly present)
            # and tobytes() gives raw pixel data
            try:
                # Use tobytes() for pixel data hash
                return hashlib.md5(obj.convert("RGB").tobytes()).hexdigest()
            except Exception:
                # Fallback for images that might have issues
                return hashlib.md5(str(obj.size).encode()).hexdigest()
        elif isinstance(obj, str):
            return hashlib.md5(obj.encode('utf-8')).hexdigest()
        else:
            return hashlib.md5(str(obj).encode('utf-8')).hexdigest()

    def generate_key(self, prompt: str, images: List[Image.Image] = None) -> str:
        """
        Generate a comprehensive MD5 hash key based on prompt and images.
        """
        # Start with prompt hash
        combined_hash_input = self._hash_obj(prompt)
        
        # Merge with image hashes if they exist
        if images:
            for img in images:
                combined_hash_input += self._hash_obj(img)
                
        # Final hash of the combined component hashes
        return hashlib.md5(combined_hash_input.encode('utf-8')).hexdigest()

    def get(self, key: str) -> Optional[Any]:
        """
        Retrieve data from cache if it exists.
        Returns deserialized JSON data or None.
        """
        cache_path = self.cache_dir / f"{key}.json"
        
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.stats['hits'] += 1
                return data
            except Exception as e:
                print(f"Cache read error for {key}: {e}")
                
        self.stats['misses'] += 1
        return None

    def set(self, key: str, value: Any):
        """
        Save data to cache.
        """
        cache_path = self.cache_dir / f"{key}.json"
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(value, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Cache write error for {key}: {e}")

    def get_stats(self) -> Dict[str, int]:
        """Return current session cache statistics."""
        return self.stats
