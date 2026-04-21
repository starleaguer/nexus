import os
import requests
from google import genai

from typing import Optional, Any

def get_structured_prompt(text: str) -> str:
    return f"""당신은 유튜브 스크립트 요약 전문가입니다 구조화하여 정리하는 요구사항입니다:. 
다음 영상 스크립트를 분석하여, 반드시 **한국어**로, 그리고 아래의 일관된 마크다운 구조를 엄격하게 지켜서 데이터 정리가 쉽도록 요약해 주세요.

---
### 📌 1. 핵심 요약 (Overview)
- 영상의 주제와 가장 중요한 결론을 2~3문장 이내로 직관적으로 요약하세요.

### 🔑 2. 주요 포인트 (Key Points)
- 영상의 핵심 내용 3~5가지를 글머리 기호(`-`)로 정리하세요.
- 각 포인트의 제목은 **굵은 글씨**로 강조하고, 간단한 부연 설명을 덧붙이세요.

### 📜 3. 세부 내용 (Detailed Summary)
- 영상의 구조와 화자의 의도를 반영해서 마치 직접 본 것처럼 요약해줘.
- 중요한 키워드나 개념은 `단어` 또는 **단어** 형태로 강조하세요.

### 💡 4. 인사이트 (Insights / Takeaways)
- 이 영상에서 얻을 수 있는 교훈, 실무 적용 방안, 또는 새롭게 알게 된 통찰을 1~2가지 작성하세요.
---
[영상 스크립트 전문]
{text}"""

def chunk_text(text: str, chunk_size: int = 4000) -> list:
    """텍스트가 너무 길 경우 메모리/컨텍스트 한계를 방지하기 위해 청킹. 
    기본 4000글자 (대략 4000~6000토큰) 단위로 분할."""
    words = text.split()
    chunks = []
    current_chunk = []
    current_length = 0
    for word in words:
        if current_length + len(word) > chunk_size:
            chunks.append(" ".join(current_chunk))
            current_chunk = [word]
            current_length = len(word)
        else:
            current_chunk.append(word)
            current_length += len(word) + 1
    if current_chunk:
        chunks.append(" ".join(current_chunk))
    # 텍스트가 너무 짧아서 청크가 없는 경우 방어 로직
    if not chunks:
        chunks.append(text)
    return chunks

def call_ollama(model_name: str, prompt: str, system: str = "", keep_alive: Optional[int] = None) -> str:
    print(f"Calling Ollama mod: {model_name} (Length: {len(prompt)})")
    payload: dict[str, Any] = {
        "model": model_name,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {
            "num_ctx": 8192
        }
    }
    
    # 메모리 스왑을 위한 keep_alive 명시적 설정
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
        
    try:
        response = requests.post('http://localhost:11434/api/generate', json=payload)
        if response.status_code == 200:
            return response.json().get('response', '')
        else:
            return f"Error: Ollama returned status {response.status_code}"
    except Exception as e:
        return f"Error calling Ollama: {e}"

def summarize_with_ollama(prompt: str, model_name: str) -> str:
    print(f"Summarizing with Ollama model: {model_name} (Single-Agent)")
    try:
        response = requests.post('http://localhost:11434/api/generate', json={
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_ctx": 8192
            }
        })
        if response.status_code == 200:
            return response.json().get('response', '')
        else:
            return f"Error: Ollama returned status {response.status_code}"
    except Exception as e:
        return f"Error calling Ollama: {e}"

def multi_agent_summarize(text: str) -> str:
    print("Starting Multi-Agent Summarization Pipeline...")
    
    # 1. Chunking
    chunks = chunk_text(text, chunk_size=4000)
    print(f"Split script into {len(chunks)} chunks.")
    
    # 2. Agent 1: Extractor (llama3.1:8b)
    extractor_model = "llama3.1:8b"
    extractor_system = "너는 데이터 추출가야. 스크립트에서 시청자 인사나 잡담은 무시해줘"
    extracted_facts = []
    
    for i, chunk in enumerate(chunks):
        print(f"Agent 1 processing chunk {i+1}/{len(chunks)}...")
        prompt = f"다음 스크립트에서 중요한 정보가 누락되지 않도록 명확하게 요약해 주세요. (1.화자의 주요 주장과 핵심 정보를 빠짐없이 포함할 것 2. 불필요한 감탄사나 반복되는 말은 제외할 것) :\n\n{chunk}"
        
        # 마지막 청크일 경우 VRAM 스왑(방출)을 위해 keep_alive=0 설정 (순차적 실행 보장)
        ka = 0 if i == len(chunks) - 1 else None 
        fact = call_ollama(extractor_model, prompt, extractor_system, keep_alive=ka)
        extracted_facts.append(fact)
        
    combined_facts = "\n\n".join(extracted_facts)
    print("Agent 1 Extraction complete. Swap to Agent 2...")
    
    # 3. Agent 2: Writer (gemma2:9b)
    writer_model = "gemma2:9b"
    writer_system = "당신은 전문 에디터입니다. Agent 1이 넘겨준 핵심 팩트들을 바탕으로 지식 베이스용으로 구조화하여 완벽하게 요약 정리하는 AI 어시스턴트입니다."
    
    writer_prompt = f"""다음은 긴 영상 스크립트에서 추출된 핵심 팩트 데이터 모음입니다.
이를 바탕으로, 반드시 **한국어**로, 그리고 아래의 일관된 마크다운 구조를 엄격하게 지켜서 데이터 정리가 쉽도록 요약해 주세요.

---
### 📌 1. 핵심 요약 (Overview)
- 영상의 주제와 가장 중요한 결론을 2~3문장 이내로 직관적으로 요약하세요.

### 🔑 2. 주요 포인트 (Key Points)
- 영상의 핵심 내용 3~5가지를 글머리 기호(`-`)로 정리하세요.
- 각 포인트의 제목은 **굵은 글씨**로 강조하고, 간단한 부연 설명을 덧붙이세요.

### 📜 3. 세부 내용 (Detailed Summary)
- 논리적 흐름이나 시간 순서에 따라 전체 내용을 2~3개의 문단으로 나누어 상세히 서술하세요.
- 중요한 키워드나 개념은 `단어` 또는 **단어** 형태로 강조하세요.

### 💡 4. 인사이트 (Insights / Takeaways)
- 이 영상에서 얻을 수 있는 교훈, 실무 적용 방안, 또는 새롭게 알게 된 통찰을 1~2가지 작성하세요.

---
[추출된 핵심 팩트 데이터]
{combined_facts}"""

    print("Agent 2 writing final structured summary...")
    # Agent 2 작업 후에도 VRAM 할당 해제
    final_summary = call_ollama(writer_model, writer_prompt, writer_system, keep_alive=0)
    
    return final_summary

def summarize_with_gemini(prompt: str, model_name: str) -> str:
    print(f"Summarizing with Gemini model: {model_name}")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "Error: GEMINI_API_KEY environment variable not set."
    
    # If the user passed an Ollama model name, fallback to a sensible Gemini default
    if model_name in ['llama3', 'mistral', 'gemma2', 'multi-agent']:
        model_name = 'gemini-2.5-flash'
        
    try:
        print(model_name)
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"Error calling Gemini: {e}"

def generate_summary(text: str, model_provider: str, model_name: str) -> str:
    if model_provider.lower() == "ollama":
        if model_name == "multi-agent":
            return multi_agent_summarize(text)
        else:
            prompt = get_structured_prompt(text)
            return summarize_with_ollama(prompt, model_name)
    elif model_provider.lower() == "gemini":
        prompt = get_structured_prompt(text)
        return summarize_with_gemini(prompt, model_name)
    else:
        return "Unsupported model provider."

