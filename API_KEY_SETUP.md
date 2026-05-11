# API Key Configuration Guide

## Dual API Key Setup

The system now uses **two separate API keys** from OpenRouter:

### 1. Vision API Key (`OPENROUTER_API_KEY`)
- **Used for**: OCR extraction with Qwen vision models
- **Models**: `qwen/qwen-2.5-vl-7b-instruct`, `qwen/qwen3-vl-8b-instruct`
- **Cost**: ~$0.10 per 1M tokens
- **Set in `.env`**:
  ```
  OPENROUTER_API_KEY=sk-or-v1-your_vision_key_here
  ```

### 2. DeepSeek API Key (`DEEPSEEK_API_KEY`)
- **Used for**: Metadata analysis and text parsing
- **Models**: `deepseek/deepseek-r1-distill-llama-70b`
- **Cost**: ~$0.23 per 1M input tokens
- **Set in `.env`**:
  ```
  DEEPSEEK_API_KEY=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
  ```

## Why Two Keys?

1. **Cost Tracking**: Separate billing for OCR vs analysis
2. **Rate Limits**: Independent quotas prevent bottlenecks
3. **Model Specialization**: Different providers may offer different models

## Fallback Behavior

If `DEEPSEEK_API_KEY` is not set, the system will fall back to `OPENROUTER_API_KEY` for all operations.

## Configuration Check

Run this to verify your setup:
```bash
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print('Vision Key:', 'SET' if os.getenv('OPENROUTER_API_KEY') else 'MISSING'); print('DeepSeek Key:', 'SET' if os.getenv('DEEPSEEK_API_KEY') else 'MISSING')"
```
