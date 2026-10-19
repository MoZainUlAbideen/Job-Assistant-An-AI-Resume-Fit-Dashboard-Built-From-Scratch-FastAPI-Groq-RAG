"""
Skill taxonomy + exact keyword matching.

WHY A TAXONOMY INSTEAD OF "ASK THE LLM FOR THE SKILL LIST"
----------------------------------------------------------
v1 asked the LLM to extract required skills on every scan. The list came out
slightly different each time ("ML" vs "Machine Learning", 4 skills vs 5), and
because the score was matched/total over a handful of skills, the same job
swung 20+ points between scans. A fixed dictionary of skills + aliases makes
extraction deterministic: same text in -> same keywords out, every time.

WHY EXACT MATCHING (WITH ALIASES) INSTEAD OF EMBEDDINGS
-------------------------------------------------------
Real ATS search is literal: a recruiter types "Kubernetes" and the system
looks for that word (or a configured synonym). Embedding similarity answers
a different question ("is this related?") and v1's thresholds were badly
calibrated for short skill names ("LLMs" vs a resume full of LangChain/Groq
scored 0.19 -> "missing"). So we split two ideas apart:

  * literal match   - the exact term or a true synonym is on the resume.
                      This is what an ATS sees.
  * implied match   - the term isn't there, but concrete evidence is
                      (PyTorch on the resume implies "Deep Learning").
                      An ATS would NOT see this -- which is exactly why it's
                      the safest thing to fix: you can honestly add the term.

WORD BOUNDARIES
---------------
v1 used substring checks (`"r" in "pytorch"` -> True). We use regex
boundaries that treat + # . as part of a token, so "C++" doesn't match
"C", "Java" doesn't match "JavaScript", and "Go"/"R"/"C" only match in
clearly list-like contexts (they're ordinary English words/letters
otherwise).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass(frozen=True)
class Skill:
    name: str                       # canonical display name
    category: str
    aliases: tuple[str, ...] = ()   # case-insensitive phrases; "re:" prefix = raw regex (case-sensitive)
    implied_by: tuple[str, ...] = ()  # canonical names whose presence is evidence for this skill
    soft: bool = False


def S(name, category, aliases=(), implied_by=(), soft=False) -> Skill:
    return Skill(name, category, tuple(aliases), tuple(implied_by), soft)


# A "list context" regex for single-letter / common-word languages:
# preceded by start, comma, slash, paren, colon or bullet; followed by comma, slash, paren, "and", or end.
_LIST_PRE = r"(?:(?<=^)|(?<=[,/(:;|•])|(?<=[,/(:;|•]\s)|(?<=\band\s))"
_LIST_POST = r"(?=\s*(?:[,/);|]|\band\b|$))"


def CS(word: str) -> str:
    """Case-sensitive whole-token alias, for skills that are also ordinary English
    words in lowercase ("react quickly", "excel at", "the rest of", "spring 2024")."""
    return "re:" + r"(?<![A-Za-z0-9+#.])" + re.escape(word) + r"(?![A-Za-z0-9+#]|\.[A-Za-z0-9])"

TAXONOMY: list[Skill] = [
    # ---------------- Languages ----------------
    S("Python", "language", ["python", "python3"]),
    S("Java", "language", ["java"]),
    S("JavaScript", "language", ["javascript", "js", "ecmascript", "es6"]),
    S("TypeScript", "language", ["typescript"]),
    S("C++", "language", ["c++", "cpp", "c/c++"]),
    S("C", "language", ["c/c++", "c programming", "c language", "re:" + _LIST_PRE + r"C" + _LIST_POST]),
    S("C#", "language", ["c#", "csharp", "c sharp"]),
    S("Go", "language", ["golang", "re:" + _LIST_PRE + r"Go" + _LIST_POST]),
    S("Rust", "language", [CS("Rust")]),
    S("R", "language", ["r programming", "r language", "rstudio", "re:" + _LIST_PRE + r"R" + _LIST_POST]),
    S("Scala", "language", ["scala"]),
    S("Kotlin", "language", ["kotlin"]),
    S("Swift", "language", [CS("Swift"), "swiftui"]),
    S("PHP", "language", ["php"]),
    S("Ruby", "language", [CS("Ruby"), "ruby on rails", "rails"]),
    S("MATLAB", "language", ["matlab"]),
    S("SQL", "language", ["sql"], implied_by=("PostgreSQL", "MySQL", "SQLite", "SQL Server", "Snowflake", "BigQuery")),
    S("Bash", "language", ["bash", "shell scripting", "shell script"]),
    S("HTML", "language", ["html", "html5"]),
    S("CSS", "language", ["css", "css3"]),
    S("Dart", "language", ["dart"]),
    S("Julia", "language", ["re:" + _LIST_PRE + r"Julia" + _LIST_POST]),
    S("Verilog", "language", ["verilog", "systemverilog", "vhdl"]),
    S("Assembly", "language", ["assembly language", "asm"]),

    # ---------------- AI / ML concepts ----------------
    S("Machine Learning", "ml", ["machine learning", "ml"],
      implied_by=("Scikit-learn", "XGBoost", "LightGBM", "Deep Learning", "PyTorch", "TensorFlow", "Keras")),
    S("Deep Learning", "ml", ["deep learning", "dl", "neural networks", "neural network"],
      implied_by=("PyTorch", "TensorFlow", "Keras", "CNN", "Transformers", "JAX")),
    S("Artificial Intelligence", "ml", ["artificial intelligence", "re:\\bAI\\b"]),
    S("LLMs", "ml", ["llm", "llms", "large language model", "large language models"],
      implied_by=("LangChain", "LlamaIndex", "OpenAI API", "Groq", "Hugging Face", "RAG", "Prompt Engineering",
                  "Fine-tuning", "Ollama", "vLLM", "Anthropic API", "LangGraph")),
    S("Generative AI", "ml", ["generative ai", "genai", "gen ai"], implied_by=("LLMs", "Diffusion Models", "RAG")),
    S("NLP", "ml", ["nlp", "natural language processing"], implied_by=("spaCy", "NLTK", "LLMs", "Transformers")),
    S("Computer Vision", "ml", ["computer vision"],
      implied_by=("OpenCV", "YOLO", "MediaPipe", "CNN", "Image Classification", "Object Detection")),
    S("Object Detection", "ml", ["object detection"], implied_by=("YOLO",)),
    S("Image Classification", "ml", ["image classification"]),
    S("RAG", "ml", ["rag", "retrieval-augmented generation", "retrieval augmented generation"],
      implied_by=("LangChain", "LlamaIndex", "Vector Databases")),
    S("Prompt Engineering", "ml", ["prompt engineering", "prompting"]),
    S("Fine-tuning", "ml", ["fine-tuning", "fine tuning", "finetuning", "lora", "qlora", "peft"]),
    S("AI Agents", "ml", ["ai agents", "ai agent", "agentic ai", "agentic", "multi-agent", "autonomous agents"],
      implied_by=("LangGraph", "CrewAI", "AutoGen")),
    S("Reinforcement Learning", "ml", ["reinforcement learning", "rlhf"]),
    S("Time Series", "ml", ["time series", "time-series", "forecasting"]),
    S("Recommendation Systems", "ml", ["recommendation systems", "recommendation system", "recommender systems",
                                       "recommender system", "recommendation engine", "recsys"]),
    S("Predictive Analytics", "ml", ["predictive analytics", "predictive modeling", "predictive modelling"]),
    S("Feature Engineering", "ml", ["feature engineering"]),
    S("CNN", "ml", ["cnn", "cnns", "convolutional neural network", "convolutional neural networks"]),
    S("Transformers", "ml", ["transformers", "transformer models", "transformer architecture", "bert"]),
    S("Diffusion Models", "ml", ["diffusion models", "stable diffusion"]),
    S("Embeddings", "ml", ["embeddings", "vector embeddings", "sentence embeddings"]),
    S("Vector Databases", "ml", ["vector database", "vector databases", "vector db", "vector store"],
      implied_by=("FAISS", "Pinecone", "Chroma", "Weaviate", "Qdrant", "Milvus", "pgvector")),
    S("MLOps", "ml", ["mlops", "ml ops", "model deployment", "model serving"],
      implied_by=("MLflow", "Kubeflow", "Weights & Biases", "BentoML", "ONNX", "TensorRT", "vLLM")),
    S("Model Evaluation", "ml", ["model evaluation", "evals", "evaluation metrics", "a/b testing", "evaluate model",
                               "evaluating models", "model quality", "performance evaluation"]),
    S("Statistics", "ml", ["statistics", "statistical analysis", "statistical modeling", "hypothesis testing"]),
    S("Data Analysis", "data", ["data analysis", "data analytics", "exploratory data analysis", "eda"],
      implied_by=("Pandas",)),
    S("Data Visualization", "data", ["data visualization", "data visualisation"],
      implied_by=("Matplotlib", "Seaborn", "Plotly", "Tableau", "Power BI", "Looker")),
    S("Data Engineering", "data", ["data engineering", "data pipelines", "data pipeline", "etl", "elt"],
      implied_by=("Airflow", "dbt", "Spark", "Kafka")),
    S("Data Modeling", "data", ["data modeling", "data modelling", "dimensional modeling", "dimensional modelling",
                                 "model data", "data models"]),

    # ---------------- ML / data libraries ----------------
    S("PyTorch", "ml_lib", ["pytorch", "torch"]),
    S("TensorFlow", "ml_lib", ["tensorflow", "tf2"]),
    S("Keras", "ml_lib", ["keras"]),
    S("JAX", "ml_lib", ["jax"]),
    S("Scikit-learn", "ml_lib", ["scikit-learn", "sklearn", "scikit learn"]),
    S("XGBoost", "ml_lib", ["xgboost"]),
    S("LightGBM", "ml_lib", ["lightgbm"]),
    S("Pandas", "ml_lib", ["pandas"]),
    S("NumPy", "ml_lib", ["numpy"]),
    S("SciPy", "ml_lib", ["scipy"]),
    S("Matplotlib", "ml_lib", ["matplotlib"]),
    S("Seaborn", "ml_lib", ["seaborn"]),
    S("Plotly", "ml_lib", ["plotly"]),
    S("OpenCV", "ml_lib", ["opencv", "cv2"]),
    S("YOLO", "ml_lib", ["yolo", "yolov5", "yolov8", "yolov11", "ultralytics yolo", "ultralytics"]),
    S("MediaPipe", "ml_lib", ["mediapipe"]),
    S("Tesseract", "ml_lib", ["tesseract", "tesseract ocr"]),
    S("Hugging Face", "ml_lib", ["hugging face", "huggingface", "hf transformers"]),
    S("spaCy", "ml_lib", ["spacy"]),
    S("NLTK", "ml_lib", ["nltk"]),
    S("LangChain", "ml_lib", ["langchain"]),
    S("LangGraph", "ml_lib", ["langgraph"]),
    S("LlamaIndex", "ml_lib", ["llamaindex", "llama index", "llama-index"]),
    S("CrewAI", "ml_lib", ["crewai", "crew ai"]),
    S("AutoGen", "ml_lib", ["autogen"]),
    S("OpenAI API", "ml_lib", ["openai api", "openai", "gpt-4", "gpt-4o", "chatgpt api"]),
    S("Anthropic API", "ml_lib", ["anthropic api", "claude api"]),
    S("Groq", "ml_lib", ["groq"]),
    S("Ollama", "ml_lib", ["ollama"]),
    S("vLLM", "ml_lib", ["vllm"]),
    S("FAISS", "ml_lib", ["faiss"]),
    S("Pinecone", "ml_lib", ["pinecone"]),
    S("Chroma", "ml_lib", [CS("Chroma"), "chromadb"]),
    S("Weaviate", "ml_lib", ["weaviate"]),
    S("Qdrant", "ml_lib", ["qdrant"]),
    S("Milvus", "ml_lib", ["milvus"]),
    S("pgvector", "ml_lib", ["pgvector"]),
    S("MLflow", "ml_lib", ["mlflow"]),
    S("Kubeflow", "ml_lib", ["kubeflow"]),
    S("Weights & Biases", "ml_lib", ["weights & biases", "weights and biases", "wandb"]),
    S("BentoML", "ml_lib", ["bentoml"]),
    S("ONNX", "ml_lib", ["onnx", "onnx runtime"]),
    S("TensorRT", "ml_lib", ["tensorrt"]),
    S("CUDA", "ml_lib", ["cuda"]),
    S("Jupyter", "tool", ["jupyter", "jupyter notebook", "jupyterlab"]),
    S("Google Colab", "tool", ["google colab", "colab"]),
    S("Streamlit", "web", ["streamlit"]),
    S("Gradio", "web", ["gradio"]),

    # ---------------- Data platforms ----------------
    S("Spark", "data", [CS("Spark"), "apache spark", "pyspark", "spark sql"]),
    S("Hadoop", "data", ["hadoop"]),
    S("Kafka", "data", ["kafka", "apache kafka"]),
    S("Airflow", "data", ["airflow", "apache airflow"]),
    S("dbt", "data", ["dbt"]),
    S("Snowflake", "data", ["snowflake"]),
    S("Databricks", "data", ["databricks"]),
    S("BigQuery", "data", ["bigquery"]),
    S("Redshift", "data", ["redshift"]),
    S("Tableau", "data", ["tableau"]),
    S("Power BI", "data", ["power bi", "powerbi"]),
    S("Looker", "data", [CS("Looker"), "looker studio"]),
    S("Excel", "data", ["microsoft excel", "ms excel", "advanced excel", "re:" + _LIST_PRE + r"Excel" + _LIST_POST]),

    # ---------------- Databases ----------------
    S("PostgreSQL", "database", ["postgresql", "postgres"]),
    S("MySQL", "database", ["mysql"]),
    S("SQLite", "database", ["sqlite"]),
    S("SQL Server", "database", ["sql server", "mssql"]),
    S("MongoDB", "database", ["mongodb", "mongo"]),
    S("Redis", "database", ["redis"]),
    S("Elasticsearch", "database", ["elasticsearch", "elastic search", "opensearch"]),
    S("DynamoDB", "database", ["dynamodb"]),
    S("Cassandra", "database", ["cassandra"]),
    S("Firebase", "database", ["firebase", "firestore"]),
    S("NoSQL", "database", ["nosql"], implied_by=("MongoDB", "DynamoDB", "Cassandra", "Redis", "Firebase")),

    # ---------------- Cloud / DevOps ----------------
    S("AWS", "cloud", ["aws", "amazon web services", "ec2", "s3", "aws lambda", "sagemaker"]),
    S("Azure", "cloud", ["azure", "microsoft azure", "azure ml"]),
    S("GCP", "cloud", ["gcp", "google cloud", "google cloud platform", "vertex ai"]),
    S("Cloud Computing", "cloud", ["cloud computing", "cloud technologies", "cloud platforms", "cloud services",
                                   "cloud infrastructure", "cloud-native", "cloud native"],
      implied_by=("AWS", "Azure", "GCP")),
    S("Docker", "devops", ["docker", "dockerfile", "containerization", "containerized"]),
    S("Kubernetes", "devops", ["kubernetes", "k8s", "eks", "gke", "aks"]),
    S("Terraform", "devops", ["terraform"]),
    S("CI/CD", "devops", ["ci/cd", "ci cd", "continuous integration", "continuous deployment", "continuous delivery"],
      implied_by=("GitHub Actions", "Jenkins", "GitLab CI")),
    S("GitHub Actions", "devops", ["github actions"]),
    S("Jenkins", "devops", ["jenkins"]),
    S("GitLab CI", "devops", ["gitlab ci", "gitlab-ci"]),
    S("Linux", "devops", ["linux", "unix", "ubuntu"]),
    S("Git", "tool", ["git", "github", "gitlab", "version control"]),
    S("Nginx", "devops", ["nginx"]),
    S("Prometheus", "devops", ["prometheus"]),
    S("Grafana", "devops", ["grafana"]),
    S("Microservices", "backend", ["microservices", "microservice", "micro-services"]),
    S("Distributed Systems", "backend", ["distributed systems", "distributed computing"]),
    S("System Design", "backend", ["system design", "software architecture"]),

    # ---------------- Backend / web ----------------
    S("REST APIs", "backend", ["rest api", "rest apis", "restful", "restful api", "restful apis", "rest-based", CS("REST")],
      implied_by=("FastAPI", "Flask", "Django", "Express")),
    S("GraphQL", "backend", ["graphql"]),
    S("gRPC", "backend", ["grpc"]),
    S("FastAPI", "backend", ["fastapi"]),
    S("Flask", "backend", [CS("Flask")]),
    S("Django", "backend", ["django"]),
    S("Node.js", "backend", ["node.js", "nodejs", "node js"]),
    S("Express", "backend", ["express.js", "expressjs", "re:" + _LIST_PRE + r"Express" + _LIST_POST]),
    S("Spring Boot", "backend", ["spring boot", "spring framework"]),
    S(".NET", "backend", [".net", "asp.net", "dotnet"]),
    S("React", "web", [CS("React"), "react.js", "reactjs"]),
    S("Next.js", "web", ["next.js", "nextjs"]),
    S("Vue", "web", [CS("Vue"), "vue.js", "vuejs"]),
    S("Angular", "web", ["angular", "angularjs"]),
    S("Figma", "web", ["figma"]),
    S("Tailwind CSS", "web", ["tailwind", "tailwind css", "tailwindcss"]),
    S("React Native", "web", ["react native"]),
    S("Flutter", "web", ["flutter"]),
    S("SQLAlchemy", "backend", ["sqlalchemy"]),
    S("Pydantic", "backend", ["pydantic"]),
    S("Celery", "backend", ["celery"]),
    S("WebSockets", "backend", ["websockets", "websocket"]),

    # ---------------- Practices ----------------
    S("Agile", "practice", ["agile", "scrum", "kanban", "sprint planning"]),
    S("Unit Testing", "practice", ["unit testing", "unit tests", "pytest", "jest", "test-driven development", "tdd"]),
    S("OOP", "practice", ["oop", "object-oriented programming", "object oriented programming", "object-oriented"]),
    S("Data Structures & Algorithms", "practice", ["data structures", "algorithms", "dsa"]),
    S("Security", "practice", ["cybersecurity", "cyber security", "information security", "security analytics",
                               "application security", "devsecops"]),

    # ---------------- Embedded / EE (relevant for an EE grad) ----------------
    S("Embedded Systems", "embedded", ["embedded systems", "embedded software", "firmware", "microcontrollers", "microcontroller"],
      implied_by=("Arduino", "Raspberry Pi", "STM32", "ESP32")),
    S("Arduino", "embedded", ["arduino"]),
    S("Raspberry Pi", "embedded", ["raspberry pi"]),
    S("ESP32", "embedded", ["esp32"]),
    S("STM32", "embedded", ["stm32"]),
    S("Signal Processing", "embedded", ["signal processing", "dsp", "digital signal processing"]),
    S("IoT", "embedded", ["iot", "internet of things"]),
    S("Sensor Fusion", "embedded", ["sensor fusion", "multi-sensor"]),

    # ---------------- Soft skills (low weight) ----------------
    S("Communication", "soft", ["communication skills", "communication", "communicate", "communicating"], soft=True),
    S("Teamwork", "soft", ["teamwork", "collaboration", "collaborate", "collaborated", "cross-functional"], soft=True),
    S("Leadership", "soft", ["leadership", "mentored", "mentoring", "lead a team", "led a team", "team lead"], soft=True),
    S("Problem Solving", "soft", ["problem solving", "problem-solving"], soft=True),
    S("Stakeholder Management", "soft", ["stakeholder management", "stakeholders", "client-facing",
                                          "clients to gather requirements"], soft=True),
]

BY_NAME: dict[str, Skill] = {s.name: s for s in TAXONOMY}


def _alias_to_regex(alias: str) -> re.Pattern:
    if alias.startswith("re:"):
        return re.compile(alias[3:], re.MULTILINE)
    escaped = re.escape(alias).replace(r"\ ", r"[\s\-]+")
    # Token boundary: not preceded/followed by a letter/digit/+/#. A trailing "."
    # is allowed after (end of sentence) but not "." + letter (so "node" != "node.js").
    return re.compile(rf"(?<![A-Za-z0-9+#.]){escaped}(?![A-Za-z0-9+#]|\.[A-Za-z0-9])", re.IGNORECASE)


@lru_cache(maxsize=1)
def _compiled() -> list[tuple[Skill, list[re.Pattern]]]:
    out = []
    for s in TAXONOMY:
        aliases = list(s.aliases) or [s.name.lower()]
        out.append((s, [_alias_to_regex(a) for a in aliases]))
    return out


@dataclass
class Hit:
    skill: str
    count: int
    spans: list[tuple[int, int]] = field(default_factory=list)


def find_skills(text: str) -> dict[str, Hit]:
    """All taxonomy skills literally present in `text` (via name or alias)."""
    hits: dict[str, Hit] = {}
    for skill, patterns in _compiled():
        spans: list[tuple[int, int]] = []
        for p in patterns:
            spans.extend(m.span() for m in p.finditer(text))
        if spans:
            # de-overlap (e.g. "c/c++" matching both C and C++ aliases is fine across skills, but
            # within one skill two aliases can hit the same span)
            spans = sorted(set(spans), key=lambda sp: (sp[0], -sp[1]))   # longest match wins at a position
            merged: list[tuple[int, int]] = []
            for a, b in spans:
                if merged and a < merged[-1][1]:
                    continue
                merged.append((a, b))
            hits[skill.name] = Hit(skill.name, len(merged), merged)
    _suppress_overlaps(hits)
    return hits


# When one skill's match is fully inside a more specific skill's match, drop the generic one
# for that span ("React Native" should not also count as "React"; "Spring Boot" fine).
_SHADOWED_BY = {
    "React": ["React Native"],
    "Spring Boot": [],
    "Security": [],
    "Git": ["GitHub Actions", "GitLab CI"],
    "REST APIs": [],
    "Transformers": ["Hugging Face"],
    "Artificial Intelligence": ["AI Agents", "Generative AI"],
}


def _suppress_overlaps(hits: dict[str, Hit]) -> None:
    for generic, specifics in _SHADOWED_BY.items():
        if generic not in hits:
            continue
        cover = [sp for s in specifics if s in hits for sp in hits[s].spans]
        if not cover:
            continue
        kept = [sp for sp in hits[generic].spans if not any(c[0] <= sp[0] and sp[1] <= c[1] for c in cover)]
        if kept:
            hits[generic] = Hit(generic, len(kept), kept)
        else:
            del hits[generic]


def implied_evidence(skill_name: str, present: set[str]) -> list[str]:
    """Which skills in `present` are evidence for `skill_name` (one level + transitive)."""
    skill = BY_NAME.get(skill_name)
    if not skill:
        return []
    found, stack, seen = [], list(skill.implied_by), set()
    while stack:
        s = stack.pop()
        if s in seen:
            continue
        seen.add(s)
        if s in present:
            found.append(s)
        elif s in BY_NAME:
            stack.extend(BY_NAME[s].implied_by)
    return sorted(found)


def contains_term(text: str, term: str) -> bool:
    """Literal, boundary-aware check for an arbitrary (possibly non-taxonomy) term."""
    if term in BY_NAME:
        return term in find_skills(text)
    return bool(_alias_to_regex(term.lower()).search(text))
